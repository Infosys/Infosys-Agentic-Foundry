import { useState, useEffect, useMemo } from 'react';
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
  const loadAvailableConnections = async () => {
    setIsLoadingConnections(true);
    try {
      const result = await fetchConnections();
      console.log('fetchConnections result:', result);
      if (result.success) {
        const connections = result.data.connections || result.data || [];
        console.log('Processed connections:', connections);
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
  };

  // Immediate update function for after connection changes
  const updateConnectionsImmediate = async () => {
    // Only update if it's been more than 1 second since last update
    if (Date.now() - lastUpdateTime > 1000) {
      await loadAvailableConnections();
    }
  };

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
  }, [lastUpdateTime]);

  // Load connections when component mounts and set up smart polling
  useEffect(() => {
    loadAvailableConnections();
    
    // Set up periodic polling (every 30 seconds)
    const pollInterval = setInterval(() => {
      loadAvailableConnections();
    }, 30000);

    // Refresh connections when window regains focus
    const handleFocus = () => {
      loadAvailableConnections();
    };
    
    window.addEventListener('focus', handleFocus);

    // Clean up interval and event listener on unmount
    return () => {
      clearInterval(pollInterval);
      window.removeEventListener('focus', handleFocus);
    };
  }, []);

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
    
    // Validate required fields
    const requiredFields = ['connectionName', 'databaseType', 'host', 'port', 'username', 'password', 'databaseName'];
    const missingFields = requiredFields.filter(field => !currentConnectionData[field] || currentConnectionData[field].trim() === '');
    if (missingFields.length > 0) {
      addMessage(`Please fill in the following required fields: ${missingFields.join(', ')}`, "error");
      return;
    }
    setIsConnecting(true);
    try {
      const payload = {
        name: currentConnectionData.connectionName,
        db_type: currentConnectionData.databaseType.toLowerCase(),
        host: currentConnectionData.host,
        port: parseInt(currentConnectionData.port),
        username: currentConnectionData.username,
        password: currentConnectionData.password,
        database: currentConnectionData.databaseName,
        flag_for_insert_into_db_connections_table: "1"
      };
      
      const apiUrl = `${BASE_URL}${APIs.CONNECT_DATABASE}`;
      try {
        const response = await axios.post(apiUrl, payload, {
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
          }
        });
        if (response.data) {
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

  const handleDisconnect = async (connectionName, databaseType) => {
    if (!connectionName || !databaseType) {
      addMessage("Connection name and database type are required for disconnection", "error");
      return;
    }

    setIsDisConnecting(true);
    
    try {
      // Prepare the API request payload for disconnect
      const payload = {
        name: connectionName,
        db_type: databaseType.toLowerCase()
      };
      
      console.log('Hook handleDisconnect - Payload:', payload);
      console.log('Hook handleDisconnect - API URL:', `${BASE_URL}${APIs.DISCONNECT_DATABASE}`);
      
      // Make the API call to disconnect
      const response = await axios.post(`${BASE_URL}${APIs.DISCONNECT_DATABASE}`, payload, {
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        }
      });
      
      console.log('Hook handleDisconnect - Response:', response.data);
      
      if (response.data) {
        
        
        // Refresh active connections to reflect the disconnection
        try {
          await fetchActiveConnections();
          
        } catch (error) {
          
        }
        
        // Refresh available connections immediately
        await updateConnectionsImmediate();
        
        // Clear selected connection
        setSelectedConnection("");
        setSelectedConnectionData(null);
        
        addMessage(response.data.message || "Database disconnected successfully!", "success");
      }
    } catch (error) {
      console.error('Hook handleDisconnect - Error:', error);
      console.error('Hook handleDisconnect - Error response:', error.response?.data);
      
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

  // Handle connection activation
  const handleActivateConnection = async (connection) => {
    
    
    setIsActivating(true);
    
    try {
      // Prepare the API request payload for activation
      const payload = {
        name: connection.connection_name,
        db_type: connection.connection_database_type.toLowerCase(),
        host: connection.connection_host,
        port: parseInt(connection.connection_port),
        username: connection.connection_username,
        password: connection.connection_password,
        database: connection.connection_database_name,
        flag_for_insert_into_db_connections_table: "0"
      };
      
      
      
      // Basic validation
      if (isNaN(payload.port) || payload.port <= 0) {
        throw new Error("Port must be a valid positive number");
      }
      
      // Check if the API endpoint is defined
      if (!APIs.CONNECT_DATABASE) {
        
        throw new Error("Database connection API endpoint not configured");
      }
      
      // Construct the URL
      const apiUrl = `${BASE_URL}${APIs.CONNECT_DATABASE}`;
      
      
      // Make the API call
      try {
       
        
        // Add a timestamp to track the request
        const requestStartTime = Date.now();
        
        
        // Test basic axios functionality
        
        try {
          const testResponse = await axios.get(BASE_URL);
          
        } catch (testError) {
          
        }
        
        // Try manual fetch as well to compare
        
        try {
          const fetchResponse = await fetch(apiUrl, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Accept': 'application/json'
            },
            body: JSON.stringify(payload)
          });
          
        } catch (fetchError) {
          
        }
        
        const response = await axios.post(apiUrl, payload, {
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
          }
        });
        
        const requestEndTime = Date.now();
        
        
        if (response.data) {
          
          
          // Add the activated database connection to our context
          addDatabase({
            name: connection.connection_name,
            type: connection.connection_database_type,
            host: connection.connection_host,
            port: connection.connection_port,
            username: connection.connection_username,
            databaseName: connection.connection_database_name
          });
          
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

 

  // Auto-refresh connections when they're accessed and stale
  const currentAvailableConnections = useMemo(() => {
    // If connections haven't been updated recently, trigger a refresh
    if (Date.now() - lastUpdateTime > 15000) { // 15 seconds
      updateConnectionsImmediate();
    }
    return availableConnections;
  }, [availableConnections, lastUpdateTime]);

  return {
    connectionData,
    setConnectionData,
    handleConnectionInputChange,
    handleConnectionSubmit,
    handleDisconnect,
    handleConnectionSelect,
    loadAvailableConnections,
    isConnecting,
    isDisConnecting,
    isActivating,
    isConnected,
    isLoadingConnections,
    availableConnections: currentAvailableConnections,
    selectedConnection,
    selectedConnectionData,
    updateConnectionsImmediate,
    handleActivateConnection
  };
};