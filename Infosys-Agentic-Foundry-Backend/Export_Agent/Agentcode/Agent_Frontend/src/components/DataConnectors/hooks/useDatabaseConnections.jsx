import { useState, useEffect, useCallback } from 'react';
import { APIs } from '../../../constant';
import { useDatabase } from '../context/DatabaseContext';
import { useMessage } from '../../../Hooks/MessageContext';
import { useDatabases } from '../service/databaseService.js';
import useFetch from '../../../Hooks/useAxios.js';

export const useDatabaseConnections = () => {
  // Use the database context
  const { addDatabase, fetchActiveConnections } = useDatabase();
  
  // Get message context for toast notifications
  const { addMessage } = useMessage();
  // Use the database service
  const { fetchConnections } = useDatabases();
  const { postData } = useFetch();

  // State for database connection form (new connections)
  const [connectionData, setConnectionData] = useState({
    connectionName: "",
    databaseType: "",
    host: "",
    port: "",
    username: "",
    password: "",
    databaseName: ""
  });

  // State for selected connection management (separate from new connection form)
  const [selectedConnection, setSelectedConnection] = useState("");
  const [selectedConnectionData, setSelectedConnectionData] = useState(null);

  // State for available connections
  const [availableConnections, setAvailableConnections] = useState([]);
  const [isLoadingConnections, setIsLoadingConnections] = useState(false);

  // Loading state for connection
  const [isConnecting, setIsConnecting] = useState(false);
  const [isDisConnecting, setIsDisConnecting] = useState(false);
  const [isConnected, setIsConnected] = useState(false);

  // State for tracking last update time to prevent unnecessary refreshes
  const [lastUpdateTime, setLastUpdateTime] = useState(Date.now());

  // State for activating connections
  const [isActivating, setIsActivating] = useState(false);

  // Fetch available connections from API
  const loadAvailableConnections = useCallback(async () => {
    setIsLoadingConnections(true);
    try {
      const result = await fetchConnections();
      
      if (result.success) {
        const connections = result.data.connections || result.data || [];
        
        setAvailableConnections(connections);
        setLastUpdateTime(Date.now());
      } else {
        console.error('Failed to fetch connections:', result.error);
        setAvailableConnections([]);
      }
    } catch (error) {
      console.error('loadAvailableConnections error:', error);
      setAvailableConnections([]);
    } finally {
      setIsLoadingConnections(false);
    }
  }, []);

  // Immediate update function for after connection changes
  const updateConnectionsImmediate = useCallback(async () => {
    // Only update if it's been more than 1 second since last update
    if (Date.now() - lastUpdateTime > 1000) {
      await loadAvailableConnections();
    }
  }, [lastUpdateTime, loadAvailableConnections]);

  // Add visibility change listener for better UX
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (!document.hidden) {
        // Tab became visible, refresh connections
        updateConnectionsImmediate();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [lastUpdateTime, updateConnectionsImmediate]);

  // Handle connection selection from dropdown
  const handleConnectionSelect = (selectedConnectionName) => {
    
    
    const selectedConn = availableConnections.find(
      conn => conn.connection_name === selectedConnectionName
    );
    
    
    
    if (selectedConn) {
      setSelectedConnection(selectedConnectionName);
      setSelectedConnectionData(selectedConn);
      
    } else {
      setSelectedConnection("");
      setSelectedConnectionData(null);
      
    }
  };

  const handleConnectionInputChange = (e) => {
   
    
    const { name, value } = e.target;
    setConnectionData(prev => {
      const newData = {
        ...prev,
        [name]: value
      };
      
      return newData;
    });
    
    // Reset connection status when user modifies the form
    if (isConnected) {
      setIsConnected(false);
    }
  };

  const handleConnectionSubmit = async (e) => {
    e.preventDefault();
    
    // Use temporary connection data if available (from DataConnectors modal)
    const currentConnectionData = window.tempConnectionData || connectionData;

    // Defensive: For SQLite, only validate the three required fields
    let requiredFields;
    if (
      currentConnectionData.databaseType &&
      currentConnectionData.databaseType.toLowerCase() === 'sqlite'
    ) {
      requiredFields = ['connectionName', 'databaseType'];
    } else {
      requiredFields = ['connectionName', 'databaseType', 'host', 'port', 'username', 'password', 'databaseName'];
    }
    const missingFields = requiredFields.filter(field => !currentConnectionData[field] || currentConnectionData[field].trim() === '');
    if (missingFields.length > 0) {
      addMessage(`Please fill in the following required fields: ${missingFields.join(', ')}`, "error");
      return;
    }
    setIsConnecting(true);
    try {
      let payload;
      if (currentConnectionData.databaseType && currentConnectionData.databaseType.toLowerCase() === 'sqlite') {
        payload = new FormData();
        payload.append('name', currentConnectionData.connectionName);
        payload.append('db_type', 'sqlite');
        payload.append('host', '');
        payload.append('port', '');
        payload.append('username', '');
        payload.append('password', '');
        payload.append('flag_for_insert_into_db_connections_table', '1');
        if (currentConnectionData.uploaded_file) {
          payload.append('sql_file', currentConnectionData.uploaded_file);
          payload.append('database', '');
        } else {
          payload.append('sql_file', '');
          payload.append('database', currentConnectionData.databaseName);
        }
      } else if (currentConnectionData.databaseType && currentConnectionData.databaseType.toLowerCase() === 'postgresql' || 
        currentConnectionData.databaseType && currentConnectionData.databaseType.toLowerCase() === 'mysql' || 
        currentConnectionData.databaseType && currentConnectionData.databaseType.toLowerCase() === 'mongodb') {
        payload = new FormData();
        payload.append('name', currentConnectionData.connectionName);
        payload.append('db_type', currentConnectionData.databaseType.toLowerCase());
        payload.append('host', currentConnectionData.host);
        payload.append('port', currentConnectionData.port);
        payload.append('username', currentConnectionData.username);
        payload.append('password', currentConnectionData.password);
        payload.append('database', currentConnectionData.databaseName);
        payload.append('flag_for_insert_into_db_connections_table', '1');
        payload.append('sql_file', '');
      }
      const apiUrl = APIs.CONNECT_DATABASE;
      try {
        const response = await postData(apiUrl, payload);
        if (response) {
          // Always refresh active connections after connect
          try {
            await fetchActiveConnections();
          } catch (error) {
            // Optionally log error
          }
          addDatabase({
            name: currentConnectionData.connectionName,
            type: currentConnectionData.databaseType,
            host: currentConnectionData.host,
            port: currentConnectionData.port,
            username: currentConnectionData.username,
            databaseName: currentConnectionData.databaseName
          });
          addMessage(response.message || "Database connected successfully!", "success");
          setIsConnected(true); // Disable the connect button after successful connection
          // Clear temporary connection data
          if (window.tempConnectionData) {
            delete window.tempConnectionData;
          }
        }
      } catch (apiError) {
        
        throw apiError;
      }
    } catch (error) {
      
      addMessage(`Connection failed`, "error");
    } finally {
      setIsConnecting(false);
    }
  };

  const handleDisconnect = async (connectionName, databaseType, flag = "1") => {
    if (!connectionName || !databaseType) {
      addMessage("Connection name and database type are required for deactivation", "error");
      return;
    }
    setIsDisConnecting(true);
    try {
      // Prepare the API request payload for disconnect
      const payload = {
        name: connectionName,
        db_type: databaseType.toLowerCase(),
        flag: flag.toString()
      };
      // Make the API call to disconnect
      const response = await postData(APIs.DISCONNECT_DATABASE, payload);
      if (response) {
        // Refresh active connections to reflect the disconnection
        try {
          await fetchActiveConnections();
        } catch (error) {}
        // Refresh available connections immediately
        await updateConnectionsImmediate();
        // Clear selected connection
        setSelectedConnection("");
        setSelectedConnectionData(null);
        addMessage(response.message, "success");
      }
    } catch (error) {
      
      // Show error message
      let errorMessage = "Failed to disconnect from database.";
      
      if (error.response) {
        errorMessage = error.response.message || 
                      error.response.error || 
                      `Server error (${error.response.status})`;
      } else if (error.request) {
        errorMessage = "No response from server. Please check if the server is running.";
      } else {
        console.error('Hook handleDisconnect - General error:', error.message);
        errorMessage = error.message;
      }
      
      addMessage(`Disconnection failed: ${errorMessage}`, "error");
    } finally {
      setIsDisConnecting(false);
    }
  };

  // Unified connect/activate function
  const handleConnectOrActivate = async (connectionData, flag = "1") => {
    setIsConnecting(true);
    try {
      let payload;
      const dbTypeValue = (connectionData.databaseType || connectionData.db_type || connectionData.connection_database_type || '').toLowerCase();
      if (dbTypeValue === 'sqlite') {
        payload = new FormData();
        payload.append('name', connectionData.connectionName || connectionData.name || connectionData.connection_name || '');
        payload.append('db_type', 'sqlite');
        payload.append('host', '');
        payload.append('port', '');
        payload.append('username', '');
        payload.append('password', '');
        payload.append('flag_for_insert_into_db_connections_table', flag);
        if (connectionData.uploaded_file) {
          payload.append('sql_file', connectionData.uploaded_file);
          payload.append('database', '');
        } else {
          payload.append('sql_file', '');
          payload.append('database', connectionData.databaseName || connectionData.database || connectionData.connection_database_name || '');
        }
      } else if (dbTypeValue === 'postgresql' || dbTypeValue === 'mysql' || dbTypeValue === 'mongodb') {
        payload = new FormData();
        payload.append('name', connectionData.connectionName || connectionData.name || connectionData.connection_name || '');
        payload.append('db_type', dbTypeValue);
        payload.append('host', connectionData.host || connectionData.connection_host || '');
        payload.append('port', connectionData.port || connectionData.connection_port || '');
        payload.append('username', connectionData.username || connectionData.connection_username || '');
        payload.append('password', connectionData.password || connectionData.connection_password || '');
        payload.append('database', connectionData.databaseName || connectionData.database || connectionData.connection_database_name || '');
        payload.append('flag_for_insert_into_db_connections_table', flag);
        payload.append('sql_file', '');
      }
      const apiUrl = APIs.CONNECT_DATABASE;
      const response = await postData(apiUrl, payload);
      if (response) {
        try { await fetchActiveConnections(); } catch {}
        await updateConnectionsImmediate();
        addMessage(response.message , "success");
        setIsConnected(flag === "1");
      }
    } catch (error) {
      addMessage(`Connection failed`, "error");
    } finally {
      setIsConnecting(false);
    }
  };

  // Handle connection activation
  const handleActivateConnection = async (connection) => {
    setIsActivating(true);
    try {
      let payload;
      if(connection.connection_database_type && connection.connection_database_type.toLowerCase() === 'sqlite'){
        payload = new FormData();
        payload.append('name', connection.connection_name);
        payload.append('db_type', 'sqlite');
        payload.append('host', '');
        payload.append('port', '');
        payload.append('username', '');
        payload.append('password', '');
        payload.append('flag_for_insert_into_db_connections_table', '0');
        if (connection.uploaded_file) {
          payload.append('sql_file', connection.uploaded_file);
          payload.append('database', '');
        } else {
          payload.append('sql_file', '');
          payload.append('database', connection.connection_database_name);
        }
      } else if (connection.connection_database_type && connection.connection_database_type.toLowerCase() === 'postgresql' || 
        connection.connection_database_type && connection.connection_database_type.toLowerCase() === 'mysql' || 
        connection.connection_database_type && connection.connection_database_type.toLowerCase() === 'mongodb') {
        payload = new FormData();
        payload.append('name', connection.connection_name);
        payload.append('db_type', connection.connection_database_type.toLowerCase());
        payload.append('host', connection.connection_host);
        payload.append('port', connection.connection_port);
        payload.append('username', connection.connection_username);
        payload.append('password', connection.connection_password);
        payload.append('database', connection.connection_database_name);
        payload.append('flag_for_insert_into_db_connections_table', '0');
        payload.append('sql_file', '');
      }
      
      
      
      // Basic validation (skip for FormData)
      if (!(payload instanceof FormData) && (isNaN(payload.port) || payload.port <= 0)) {
        throw new Error("Port must be a valid positive number");
      }
      
      // Check if the API endpoint is defined
      if (!APIs.CONNECT_DATABASE) {
        throw new Error("Database connection API endpoint not configured");
      }
      try{
      // Construct the URL
      const apiUrl = APIs.CONNECT_DATABASE;

        const response = await postData(apiUrl, payload);

        // Check for error fields in the response
        if (response && (response.detail || response.error)) {
          addMessage(response.detail || response.error, "error");
          return;
        }

        if (response) {
          
          
          // Add the activated database connection to our context
          if (payload.db_type === 'sqlite') {
            addDatabase({
              name: payload.name,
              type: 'sqlite',
              host: '',
              port: '',
              username: '',
              databaseName: payload.database
            });
          } else {
            addDatabase({
              name: connection.connection_name,
              type: connection.connection_database_type,
              host: connection.connection_host,
              port: connection.connection_port,
              username: connection.connection_username,
              databaseName: connection.connection_database_name
            });
          }
          
          // Refresh active connections to show the newly activated connection
          try {
            await fetchActiveConnections();
            
          } catch (error) {
            
          }
          
          // Refresh available connections to update the dropdown immediately
          try {
            await updateConnectionsImmediate();
            
          } catch (error) {
            
          }
          
          addMessage(response.message || `Connection "${connection.connection_name}" activated successfully!`, "success");
          
        } else {
          
          addMessage("API response received but no data", "warning");
        }
      } catch (apiError) {
        // Show error message from backend if available
        let errorMessage = "Failed to activate connection. Please try again.";
        if (apiError.response && (apiError.response.detail || apiError.response.error)) {
          errorMessage = apiError.response.detail || apiError.response.error;
        } else if (apiError.response) {
          errorMessage = apiError.response.message || `Server error (${apiError.response.status})`;
        } else if (apiError.request) {
          errorMessage = "No response from server. Please check if the server is running.";
        } else {
          errorMessage = apiError.message;
        }
        addMessage(`Connection activation failed: ${errorMessage}`, "error");
      }
    } catch (error) {
      
      
      // Show error message
      let errorMessage = "Failed to activate connection. Please try again.";
      if (error.response) {
        errorMessage = error.response.message || error.response.error || `Server error (${error.response.status})`;
      } else if (error.request) {
        
        errorMessage = "No response from server. Please check if the server is running.";
      } else {
      
        errorMessage = error.message;
      }
      
      addMessage(`Connection activation failed: ${errorMessage}`, "error");
    } finally {
      setIsActivating(false);
    }
  };

  // Handle deactivate connection (flag = "0")
  const handleDeactivate = async (connectionName, databaseType, flag = "0") => {
    if (!connectionName || !databaseType) {
      addMessage("Connection name and database type are required for deactivation", "error");
      return;
    }
    setIsDisConnecting(true);
    try {
      // Prepare the API request payload for deactivate
      const payload = {
        name: connectionName,
        db_type: databaseType.toLowerCase(),
        flag: flag.toString()
      };
      const response = await postData(APIs.DISCONNECT_DATABASE, payload);
      if (response) {
        // Refresh active connections to reflect the deactivation
        try {
          await fetchActiveConnections();
        } catch (error) {}
        // Refresh available connections immediately
        await updateConnectionsImmediate();
        // Clear selected connection
        setSelectedConnection("");
        setSelectedConnectionData(null);
        addMessage(response.message || "Database deactivated successfully!", "success");
      }
    } catch (error) {
      
      // Show error message
      let errorMessage = "Failed to deactivate connection.";
      
      if (error.response) {
        errorMessage = error.response.message || 
                      error.response.error || 
                      `Server error (${error.response.status})`;
      } else if (error.request) {
        errorMessage = "No response from server. Please check if the server is running.";
      } else {
        errorMessage = error.message;
      }
      addMessage("Deactivation failed", "error");
    } finally {
      setIsDisConnecting(false);
    }
  };

  return {
    connectionData,
    setConnectionData,
    selectedConnection,
    selectedConnectionData,
    availableConnections,
    isLoadingConnections,
    isConnecting,
    isDisConnecting,
    isConnected,
    isActivating,
    loadAvailableConnections,
    handleConnectionSelect,
    handleConnectionInputChange,
    handleConnectionSubmit,
    handleDisconnect,
    handleConnectOrActivate,
    handleActivateConnection,
    handleDeactivate
  };
};