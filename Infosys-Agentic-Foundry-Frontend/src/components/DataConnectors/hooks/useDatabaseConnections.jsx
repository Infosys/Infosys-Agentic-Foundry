import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { BASE_URL, APIs } from '../../../constant';
import { useDatabase } from '../context/DatabaseContext';
import { useMessage } from '../../../Hooks/MessageContext';
import { fetchConnections } from '../../../services/databaseService';

export const useDatabaseConnections = () => {
  // Use the database context
  const { addDatabase, fetchActiveConnections } = useDatabase();
  
  // Get message context for toast notifications
  const { addMessage } = useMessage();
  
  
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

  // Helper for sqlite payload
  function buildSqlitePayloadForApi(connectionName, dbType, database, flag) {
    return {
      name: connectionName || '',
      db_type: 'sqlite', // always force sqlite
      database: database || '',
      port: 0,
      host: '',
      username: '',
      password: '',
      flag_for_insert_into_db_connections_table: flag
    };
  }

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
      if (currentConnectionData.databaseType.toLowerCase() === 'sqlite') {
        // If file is uploaded, use its name as database
        let dbValue = currentConnectionData.uploaded_file
          ? currentConnectionData.uploaded_file.name
          : currentConnectionData.databaseName;
        payload = buildSqlitePayloadForApi(
          currentConnectionData.connectionName,
          currentConnectionData.databaseType,
          dbValue,
          "1"
        );
      } else {
        payload = {
          name: currentConnectionData.connectionName,
          db_type: currentConnectionData.databaseType.toLowerCase(),
          host: currentConnectionData.host,
          port: parseInt(currentConnectionData.port),
          username: currentConnectionData.username,
          password: currentConnectionData.password,
          database: currentConnectionData.databaseName,
          flag_for_insert_into_db_connections_table: "1"
        };
      }
      
      const apiUrl = `${BASE_URL}${APIs.CONNECT_DATABASE}`;
      try {
        const response = await axios.post(apiUrl, payload, {
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
          }
        });
        if (response.data) {
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
          addMessage(response.data.message || "Database connected successfully!", "success");
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
      const response = await axios.post(`${BASE_URL}${APIs.DISCONNECT_DATABASE}`, payload, {
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        }
      });
      if (response.data) {
        // Refresh active connections to reflect the disconnection
        try {
          await fetchActiveConnections();
        } catch (error) {}
        // Refresh available connections immediately
        await updateConnectionsImmediate();
        // Clear selected connection
        setSelectedConnection("");
        setSelectedConnectionData(null);
        addMessage(response.data.message, "success");
      }
    } catch (error) {
      
      // Show error message
      let errorMessage = "Failed to disconnect from database.";
      
      if (error.response) {
        console.error('Hook handleDisconnect - Response error:', error.response.status, error.response.data);
        errorMessage = error.response.data?.message || 
                      error.response.data?.error || 
                      `Server error (${error.response.status})`;
      } else if (error.request) {
        console.error('Hook handleDisconnect - Request error:', error.request);
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
        let name = connectionData.connection_name || connectionData.connectionName || '';
        if (!name || name.trim() === '') name = 'sqlite_db';
        let database = connectionData.connection_database_name || connectionData.databaseName || connectionData.database || '';
        if (!database || database.trim() === '') database = name;
        let db_type = 'sqlite';
        payload = {
          name,
          db_type,
          database,
          port: 0,
          host: '',
          username: '',
          password: '',
          flag_for_insert_into_db_connections_table: flag
        };
      } else {
        payload = {
          name: connectionData.connectionName || connectionData.name || connectionData.connection_name || '',
          db_type: (connectionData.databaseType || connectionData.db_type || connectionData.connection_database_type || '').toLowerCase(),
          host: connectionData.host || connectionData.connection_host || '',
          port: parseInt(connectionData.port || connectionData.connection_port) || 0,
          username: connectionData.username || connectionData.connection_username || '',
          password: connectionData.password || connectionData.connection_password || '',
          database: connectionData.databaseName || connectionData.database || connectionData.connection_database_name || '',
          flag_for_insert_into_db_connections_table: flag
        };
      }
      const apiUrl = `${BASE_URL}${APIs.CONNECT_DATABASE}`;
      const response = await axios.post(apiUrl, payload, {
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        }
      });
      if (response.data) {
        try { await fetchActiveConnections(); } catch {}
        await updateConnectionsImmediate();
        addMessage(response.data.message || (flag === "0" ? "Database activated successfully!" : "Database connected successfully!"), "success");
        setIsConnected(flag === "1");
      }
    } catch (error) {
      addMessage(`Connection failed: ${error.message || error}`, "error");
    } finally {
      setIsConnecting(false);
    }
  };

  // Handle connection activation
  const handleActivateConnection = async (connection) => {
    setIsActivating(true);
    try {
      let payload;
      if(connection.databasetype.toLowerCase() === 'sqlite'){
     payload = {
          name: connection.connection_name,
          db_type: "sqlite",
          host: "",
          port: 0, // SQLite does not use port
          username:"",
          password: "",
          database:connection.connection_database_name,
          flag_for_insert_into_db_connections_table: "0"
        };
      }else {
        payload = {
          name: connection.connection_name,
          db_type: connection.connection_database_type ? connection.connection_database_type.toLowerCase() : '',
          host: connection.connection_host,
          port: parseInt(connection.connection_port),
          username: connection.connection_username,
          password: connection.connection_password,
          database: connection.connection_database_name,
          flag_for_insert_into_db_connections_table: "0"
        };
      }
      
      
      
      // Basic validation
      if (isNaN(payload.port) || payload.port <= 0) {
        throw new Error("Port must be a valid positive number");
      }
      
      // Check if the API endpoint is defined
      if (!APIs.CONNECT_DATABASE) {
        
        throw new Error("Database connection API endpoint not configured");
      }
      try{
      // Construct the URL
      const apiUrl = `${BASE_URL}${APIs.CONNECT_DATABASE}`;
        
        const response = await axios.post(apiUrl, payload, {
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
          }
        });
        
        
        if (response.data) {
          
          
          // Add the activated database connection to our context
          if (payload.db_type === 'sqlite') {
            addDatabase({
              name: payload.name,
              type: 'sqlite',
              host: '',
              port: 0,
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
          
          addMessage(response.data.message || `Connection "${connection.connection_name}" activated successfully!`, "success");
          
        } else {
          
          addMessage("API response received but no data", "warning");
        }
      } catch (apiError) {
        
        throw apiError;
      }
    } catch (error) {
      
      
      // Show error message
      let errorMessage = "Failed to activate connection. Please try again.";
      
      if (error.response) {
        
        errorMessage = error.response.data?.message || 
                      error.response.data?.error || 
                      `Server error (${error.response.status})`;
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
      const response = await axios.post(`${BASE_URL}${APIs.DISCONNECT_DATABASE}`, payload, {
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        }
      });
      if (response.data) {
        // Refresh active connections to reflect the deactivation
        try {
          await fetchActiveConnections();
        } catch (error) {}
        // Refresh available connections immediately
        await updateConnectionsImmediate();
        // Clear selected connection
        setSelectedConnection("");
        setSelectedConnectionData(null);
        addMessage(response.data.message || "Database deactivated successfully!", "success");
      }
    } catch (error) {
      
      // Show error message
      let errorMessage = "Failed to deactivate connection.";
      
      if (error.response) {
        console.error('Hook handleDeactivate - Response error:', error.response.status, error.response.data);
        errorMessage = error.response.data?.message || 
                      error.response.data?.error || 
                      `Server error (${error.response.status})`;
      } else if (error.request) {
        console.error('Hook handleDeactivate - Request error:', error.request);
        errorMessage = "No response from server. Please check if the server is running.";
      } else {
        console.error('Hook handleDeactivate - General error:', error.message);
        errorMessage = error.message;
      }
      
      addMessage(`Deactivation failed: ${errorMessage}`, "error");
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