import { APIs } from '../../../constant.js';
import useFetch from '../../../Hooks/useAxios';
import { getEmailFromToken } from '../../../utils/jwtUtils';

export const useDatabases = () => {
    const {fetchData,postData,putData,deleteData} = useFetch();

const generateQuery = async (databaseType, naturalLanguageQuery) => {
  try {
    const requestBody = {
      database_type: databaseType,
      natural_language_query: naturalLanguageQuery
    };
    const response = await postData(APIs.GENERATE_QUERY, requestBody);
    return {
      success: true,
      data: response
    };
  } catch (error) {
    return {
      success: false,
      error: error.response?.message || error.message || 'Failed to generate query'
    };
  }
};

const executeQuery = async (connectionName, query) => {
  try {
    const requestBody = {
      name: connectionName,
      data: btoa(query),  // Encoded query with key name changed to 'data'
      created_by: getEmailFromToken(),
    };
    const response = await postData(APIs.RUN_QUERY, requestBody);
    return {
      success: true,
      data: response
    };
  } catch (error) {
    let errorMessage = 'Failed to execute query';
    
    if (error.response?.status === 404) {
      errorMessage = 'Connection not found. Please ensure the database is connected and the connection name is correct.';
    } else if (error.response?.detail) {
      errorMessage = error.response.detail;
    } else if (error.response?.message) {
      errorMessage = error.response.message;
    } else if (error.message) {
      errorMessage = error.message;
    }
    
    return {
      success: false,
      error: errorMessage
    };
  }
};

const fetchConnections = async () => {
  try {
    const response = await fetchData(APIs.AVAILABLE_CONNECTIONS);
    return {
      success: true,
      data: response
    };
  } catch (error) {
    console.error('Fetch connections error:', error);
    return {
      success: false,
      error: error.response?.message || error.message || 'Failed to fetch connections'
    };
  }
};

const fetchSqlConnections = async () => {
  try {
    const response = await fetchData(APIs.SQL_CONNECTIONS);
    return {
      success: true,
      data: response
    };
  } catch (error) {
    
    return {
      success: false,
      error: error.response?.message || error.message || 'Failed to fetch SQL connections'
    };
  }
};

const fetchMongodbConnections = async () => {
  try {
    const response = await fetchData(APIs.MONGODB_CONNECTIONS);

    return {
      success: true,
      data: response
    };
  } catch (error) {
    
    return {
      success: false,
      error: error.response?.message || error.message || 'Failed to fetch MongoDB connections'
    };
  }
};

const executeMongodbOperation = async (operationData) => {
  try {
    // Validate payload before sending
    const requiredFields = ['conn_name', 'collection', 'operation', 'mode'];
    const missingFields = requiredFields.filter(field => !operationData[field]);
    if (missingFields.length > 0) {
      throw new Error(`Missing required fields: ${missingFields.join(', ')}`);
    }

    const response = await postData(APIs.MONGODB_OPERATION, operationData);

    return {
      success: true,
      data: response
    };
  } catch (error) {
    
    let errorMessage = 'Failed to execute MongoDB operation';
    
    if (error.code === 'ECONNREFUSED') {
      errorMessage = 'Connection refused. The MongoDB operation endpoint may not be available.';
    } else if (error.code === 'ENOTFOUND') {
      errorMessage = 'Network error. Cannot reach the server';
    } else if (error.code === 'ECONNABORTED') {
      errorMessage = 'Request timeout. The MongoDB operation took too long to complete.';
    } else if (error.response?.status === 404) {
      errorMessage = 'MongoDB operation endpoint not found. Please check if the /mongodb-operation/ endpoint exists.';
    } else if (error.response?.status === 405) {
      errorMessage = 'Method not allowed. The /mongodb-operation/ endpoint may not accept POST requests.';
    } else if (error.response?.status === 422) {
      errorMessage = `Validation error: ${JSON.stringify(error.response)}`;
    } else if (error.response?.status === 500) {
      errorMessage = `Internal server error: ${error.response.detail || 'Check server logs'}`;
    } else if (error.response?.detail) {
      errorMessage = error.response.detail;
    } else if (error.response?.message) {
      errorMessage = error.response.message;
    } else if (error.message) {
      errorMessage = error.message;
    }
    
    return {
      success: false,
      error: errorMessage
    };
  }
};

const activateConnection = async (connectionName) => {
  try {
    const requestBody = {
      connection_name: connectionName
    };
    const config = {
      headers: {
        "Content-Type": "application/x-www-form-urlencoded"
      }
    };
    const response = await postData(APIs.ACTIVATE_CONNECTION, requestBody, config);
    return {
      success: true,
      data: response
    };
  } catch (error) {
    return {
      success: false,
      error: error.response?.message || error.message || 'Failed to activate connection'
    };
  }
};

// ============ DB Details API ============

const getDbDetails = async (connectionName) => {
  try {
    const response = await fetchData(
      APIs.GET_DB_DETAILS + encodeURIComponent(connectionName),
      { silent: true }
    );
    return { success: true, data: response };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || error.response?.message || error.message || "Failed to fetch connection details"
    };
  }
};

// ============ Blocked Commands APIs ============

const getBlockedCommands = async (connectionName) => {
  try {
    const response = await fetchData(
      APIs.GET_BLOCKED_COMMANDS + encodeURIComponent(connectionName),
      { silent: true }
    );
    return { success: true, data: response };
  } catch (error) {
    return {
      success: false,
      error: error.response?.data?.detail || error.response?.message || error.message || 'Failed to fetch blocked commands'
    };
  }
};

const updateBlockedCommands = async (connectionName, commands) => {
  try {
    const response = await putData(
      APIs.UPDATE_BLOCKED_COMMANDS + encodeURIComponent(connectionName),
      commands,
      { silent: true }
    );
    return { success: true, data: response };
  } catch (error) {
    const detail = error.response?.data?.detail;
    let errorMsg = "Failed to update blocked commands";
    if (typeof detail === "string") {
      errorMsg = detail;
    } else if (Array.isArray(detail) && detail.length > 0) {
      errorMsg = detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
    } else if (error.response?.message) {
      errorMsg = error.response.message;
    } else if (error.message) {
      errorMsg = error.message;
    }
    return { success: false, error: errorMsg };
  }
};

// ============ Schema & Samples APIs ============

const regenerateSchema = async (connectionName) => {
  try {
    const response = await postData(
      APIs.REGENERATE_SCHEMA_SAMPLES + encodeURIComponent(connectionName),
      {},
      { silent: true }
    );
    return { success: true, data: response };
  } catch (error) {
    const detail = error.response?.data?.detail;
    let errorMsg = "Failed to regenerate schema";
    if (typeof detail === "string") {
      errorMsg = detail;
    } else if (Array.isArray(detail) && detail.length > 0) {
      errorMsg = detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
    } else if (error.response?.message) {
      errorMsg = error.response.message;
    } else if (error.message) {
      errorMsg = error.message;
    }
    return { success: false, error: errorMsg };
  }
};

const listDbFiles = async (connectionName) => {
  try {
    const url = connectionName
      ? `${APIs.LIST_DB_FILES}?connection_name=${encodeURIComponent(connectionName)}`
      : APIs.LIST_DB_FILES;
    const response = await fetchData(url);
    return { success: true, data: response };
  } catch (error) {
    return {
      success: false,
      error: error.response?.message || error.message || 'Failed to list database files'
    };
  }
};

const clearDbFiles = async (connectionName) => {
  try {
    const response = await deleteData(APIs.CLEAR_DB_FILES + encodeURIComponent(connectionName));
    return { success: true, data: response };
  } catch (error) {
    return {
      success: false,
      error: error.response?.message || error.message || 'Failed to clear database files'
    };
  }
};

return {
  generateQuery, executeQuery, fetchConnections, fetchSqlConnections,
  fetchMongodbConnections, executeMongodbOperation, activateConnection,
  getDbDetails, getBlockedCommands, updateBlockedCommands, regenerateSchema,
  listDbFiles, clearDbFiles,
};
};
