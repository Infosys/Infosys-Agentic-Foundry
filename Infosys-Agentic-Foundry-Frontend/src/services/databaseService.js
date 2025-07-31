import axios from 'axios';
import { BASE_URL, APIs } from '../constant';
import { getCsrfToken, getSessionId} from "../Hooks/useAxios";

export const generateQuery = async (databaseType, naturalLanguageQuery) => {
  try {
    const response = await axios.post(`${BASE_URL}${APIs.GENERATE_QUERY}`, {
      database_type: databaseType,
      natural_language_query: naturalLanguageQuery
    }, {
      headers: {
        'accept': 'application/json',
        'Content-Type': 'application/json',
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      }
    });
    
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.message || error.message || 'Failed to generate query'
    };
  }
};

export const executeQuery = async (connectionName, query) => {
  try {
    const requestBody = {
      name: connectionName,
      query: query
    };
    
    
    const response = await axios.post(`${BASE_URL}${APIs.RUN_QUERY}`, requestBody, {
      headers: {
        'accept': 'application/json',
        'Content-Type': 'application/json',
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      }
    });
    
    
    
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    
    
    let errorMessage = 'Failed to execute query';
    
    if (error.response?.status === 404) {
      errorMessage = 'Connection not found. Please ensure the database is connected and the connection name is correct.';
    } else if (error.response?.data?.detail) {
      errorMessage = error.response.data.detail;
    } else if (error.response?.data?.message) {
      errorMessage = error.response.data.message;
    } else if (error.message) {
      errorMessage = error.message;
    }
    
    return {
      success: false,
      error: errorMessage
    };
  }
};

export const fetchConnections = async () => {
  try {
    const response = await axios.get(`${BASE_URL}${APIs.AVAILABLE_CONNECTIONS}`, {
      headers: {
        'accept': 'application/json',
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      }
    });
    
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    console.error('Fetch connections error:', error);
    return {
      success: false,
      error: error.response?.data?.message || error.message || 'Failed to fetch connections'
    };
  }
};

export const fetchSqlConnections = async () => {
  try {
    const response = await axios.get(`${BASE_URL}${APIs.SQL_CONNECTIONS}`, {
      headers: {
        'accept': 'application/json',
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      }
    });
    
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    
    return {
      success: false,
      error: error.response?.data?.message || error.message || 'Failed to fetch SQL connections'
    };
  }
};

export const fetchMongodbConnections = async () => {
  try {
    const response = await axios.get(`${BASE_URL}${APIs.MONGODB_CONNECTIONS}`, {
      headers: {
        'accept': 'application/json',
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
        
      }
    });
    
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    
    return {
      success: false,
      error: error.response?.data?.message || error.message || 'Failed to fetch MongoDB connections'
    };
  }
};

export const executeMongodbOperation = async (operationData) => {
  try {
    const url = `${BASE_URL}${APIs.MONGODB_OPERATION}`;
    
    // Validate payload before sending
    const requiredFields = ['conn_name', 'collection', 'operation', 'mode'];
    const missingFields = requiredFields.filter(field => !operationData[field]);
    if (missingFields.length > 0) {
      throw new Error(`Missing required fields: ${missingFields.join(', ')}`);
    }
    
    const response = await axios.post(url, operationData, {
      headers: {
        'accept': 'application/json',
        'Content-Type': 'application/json',
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      },
      timeout: 30000 // 30 second timeout
    });
    
    
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    
    let errorMessage = 'Failed to execute MongoDB operation';
    
    if (error.code === 'ECONNREFUSED') {
      errorMessage = 'Connection refused. The MongoDB operation endpoint may not be available.';
    } else if (error.code === 'ENOTFOUND') {
      errorMessage = 'Network error. Cannot reach the server at http://10.779.18.602:5001';
    } else if (error.code === 'ECONNABORTED') {
      errorMessage = 'Request timeout. The MongoDB operation took too long to complete.';
    } else if (error.response?.status === 404) {
      errorMessage = 'MongoDB operation endpoint not found. Please check if the /mongodb-operation/ endpoint exists.';
    } else if (error.response?.status === 405) {
      errorMessage = 'Method not allowed. The /mongodb-operation/ endpoint may not accept POST requests.';
    } else if (error.response?.status === 422) {
      errorMessage = `Validation error: ${JSON.stringify(error.response.data)}`;
    } else if (error.response?.status === 500) {
      errorMessage = `Internal server error: ${error.response.data?.detail || 'Check server logs'}`;
    } else if (error.response?.data?.detail) {
      errorMessage = error.response.data.detail;
    } else if (error.response?.data?.message) {
      errorMessage = error.response.data.message;
    } else if (error.message) {
      errorMessage = error.message;
    }
    
    return {
      success: false,
      error: errorMessage
    };
  }
};

// Helper to build SQLite payload for activate/connect
function buildSqlitePayload(connectionName, connectionData, flag) {
  return {
    name: connectionData.connectionName || connectionData.name || connectionName,
    db_type: 'sqlite',
    host: '',
    port: 0, // always 0 for sqlite
    username: '',
    password: '',
    database: connectionData.databaseName || connectionData.database || '',
    flag_for_insert_into_db_connections_table: flag
  };
}

export const connectDatabase = async (databaseType, connectionData) => {
  try {
    let requestBody;
    if (databaseType && databaseType.toLowerCase() === 'sqlite') {
      requestBody = buildSqlitePayload(null, connectionData, "1");
    } else {
      requestBody = {
        database_type: databaseType,
        ...connectionData
      };
    }
    
    const response = await axios.post(`${BASE_URL}${APIs.CONNECT_DATABASE}`, requestBody, {
      headers: {
        'accept': 'application/json',
        'Content-Type': 'application/json',
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      }
    });
    
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    let errorMessage = 'Failed to connect to database';
    
    if (error.response?.status === 400) {
      errorMessage = 'Invalid connection parameters. Please check your configuration.';
    } else if (error.response?.status === 401) {
      errorMessage = 'Authentication failed. Please check your credentials.';
    } else if (error.response?.status === 404) {
      errorMessage = 'Database server not found. Please check the host and port.';
    } else if (error.response?.status === 500) {
      errorMessage = 'Database connection failed. Please check if the database is running.';
    } else if (error.response?.data?.detail) {
      errorMessage = error.response.data.detail;
    } else if (error.response?.data?.message) {
      errorMessage = error.response.data.message;
    } else if (error.message) {
      errorMessage = error.message;
    }
    
    return {
      success: false,
      error: errorMessage
    };
  }
};

export const disconnectDatabase = async (connectionName, connectionData) => {
  try {
    
    // Try multiple ways to get the database type
    let dbType = connectionData.databaseType || 
                 connectionData.db_type || 
                 connectionData.type || 
                 connectionData.database_type;
    
    // If still null, try to infer from connection name or other properties
    if (!dbType) {
      // Check if there's a pattern in the connection name
      const nameStr = (connectionData.connectionName || connectionData.name || connectionName || '').toLowerCase();
      if (nameStr.includes('postgres') || nameStr.includes('pg')) {
        dbType = 'postgresql';
      } else if (nameStr.includes('mysql')) {
        dbType = 'mysql';
      } else if (nameStr.includes('mongo')) {
        dbType = 'mongodb';
      } else if (nameStr.includes('sqlite')) {
        dbType = 'sqlite';
      }
    }
    
    // If still null, check the port to infer database type
    if (!dbType && connectionData.port) {
      const port = parseInt(connectionData.port);
      switch (port) {
        case 5432:
          dbType = 'postgresql';
          break;
        case 3306:
          dbType = 'mysql';
          break;
        case 27017:
          dbType = 'mongodb';
          break;
        default:
          break;
      }
    }
    
    const payload = {
      name: connectionData.connectionName || connectionData.name || connectionName,
      db_type: dbType ? dbType.toLowerCase() : null
    };
    
    // Validate that we have the required parameters
    if (!payload.name || !payload.db_type) {
      console.error('Missing required parameters for disconnect:', payload);
      throw new Error(`Missing required parameters: name=${payload.name}, db_type=${payload.db_type}`);
    }
    
    const response = await axios.post(`${BASE_URL}${APIs.DISCONNECT_DATABASE}`, payload, {
      headers: {
        'accept': 'application/json',
        'Content-Type': 'application/json',
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      }
    });
    
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    console.error('Disconnect database error:', error);
    console.error('Error response:', error.response?.data);
    return {
      success: false,
      error: error.response?.data?.message || error.message || 'Failed to disconnect database'
    };
  }
};

export const activateDatabase = async (connectionName, connectionData) => {
  try {
    // Get default port based on database type if port is not provided
    const getDefaultPort = (dbType) => {
      switch (dbType?.toLowerCase()) {
        case 'postgresql': return 5432;
        case 'mysql': return 3306;
        case 'mongodb': return 27017;
        case 'sqlite': return null;
        default: return null;
      }
    };
    
    const dbType = connectionData.databaseType || connectionData.db_type;
    let payload;
    if (dbType && dbType.toLowerCase() === 'sqlite') {
      payload = buildSqlitePayload(connectionName, connectionData, "0");
    } else {
      const port = connectionData.port ? parseInt(connectionData.port) : getDefaultPort(dbType);
      payload = {
        name: connectionData.connectionName || connectionData.name || connectionName,
        db_type: dbType ? dbType.toLowerCase() : '',
        host: connectionData.host || '',
        port: port || 0,
        username: connectionData.username || '',
        password: connectionData.password || '',
        database: connectionData.databaseName || connectionData.database || '',
        flag_for_insert_into_db_connections_table: "0"
      };
    }
    
    const response = await axios.post(`${BASE_URL}${APIs.CONNECT_DATABASE}`, payload, {
      headers: {
        'accept': 'application/json',
        'Content-Type': 'application/json',
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      }
    });
    
    // Check if response indicates success
    if (response.status === 200 || response.status === 201) {
      return {
        success: true,
        data: response.data
      };
    } else {
      console.error('Activate Database - Unexpected response status:', response.status);
      return {
        success: false,
        error: `Unexpected response status: ${response.status}`
      };
    }
    
  } catch (error) {
    console.error('Activate database error:', error);
    console.error('Error response status:', error.response?.status);
    console.error('Error response data:', error.response?.data);
    console.error('Error message:', error.message);
    
    let errorMessage = 'Failed to activate database';
    if (error.response?.data?.message) {
      errorMessage = error.response.data.message;
    } else if (error.response?.data?.detail) {
      errorMessage = error.response.data.detail;
    } else if (error.message) {
      errorMessage = error.message;
    }
    
    return {
      success: false,
      error: errorMessage
    };
  }
};

export const getActiveConnections = async () => {
  try {
    const response = await axios.get(`${BASE_URL}${APIs.GET_ACTIVE_CONNECTIONS}`, {
      headers: {
        'accept': 'application/json',
        "csrf-token": getCsrfToken(),
        "session-id": getSessionId(), // added for CSRF token implementation
      }
    });
    
    return {
      success: true,
      data: response.data
    };
  } catch (error) {
    console.error('Get active connections error:', error);
    return {
      success: false,
      error: error.response?.data?.message || error.message || 'Failed to get active connections'
    };
  }
};