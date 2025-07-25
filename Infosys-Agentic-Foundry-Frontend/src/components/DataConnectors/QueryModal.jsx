import React, { useState, useEffect } from "react";
import styles from "./QueryModal.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { useDatabase } from "./context/DatabaseContext";
import { fetchSqlConnections, generateQuery, executeQuery } from "../../services/databaseService";
import { useMessage } from "../../Hooks/MessageContext";
import Loader from "../commonComponents/Loader.jsx";

const QueryModal = ({ database, onClose, onRunQuery, isExecuting }) => {
  const [queryData, setQueryData] = useState({
    selectedConnection: "",
    naturalLanguageQuery: "",
    generatedQuery: "",
    showGeneratedQuery: false,
    showResult: false,
    queryResult: null,
    error: null,
  });

  const [isGenerating, setIsGenerating] = useState(false);
  const [sqlConnections, setSqlConnections] = useState([]);
  const [loadingSqlConnections, setLoadingSqlConnections] = useState(false);
  const { setShowPopup } = useMessage();
  const [showResponseModal, setShowResponseModal] = useState(false);

  // Use the database context
  const {  } = useDatabase();
  const { addMessage } = useMessage();

  // Fetch SQL connections from API
  const fetchSqlConnectionsData = async () => {
    setLoadingSqlConnections(true);
    try {
      const result = await fetchSqlConnections();
      if (result.success) {
        setSqlConnections(result.data.connections || []);
      } else {
        setSqlConnections([]);
      }
    } catch (error) {
      setSqlConnections([]);
    } finally {
      setLoadingSqlConnections(false);
    }
  };

  // Fetch connections when component mounts
  useEffect(() => {
    fetchSqlConnectionsData();
  }, []);

  // Toggle popup based on isExecuting prop
  useEffect(() => {
    if (!isExecuting) {
      setShowPopup(true);
    } else {
      setShowPopup(false);
    }
  }, [isExecuting, setShowPopup]);

  // Handle input changes
  const handleQueryInputChange = (e) => {
    const { name, value } = e.target;
    setQueryData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  // Get selected database type
  const getSelectedDatabaseType = () => {
    const allConnections = getAllAvailableConnections();
    const selectedConn = allConnections.find(conn => conn.value === queryData.selectedConnection);
    return selectedConn ? selectedConn.type : '';
  };

  // Map database ID to database type for filtering
  const getDatabaseTypeFromId = (databaseId) => {
    const typeMapping = {
      'postgresql': 'PostgreSQL',
      'mysql': 'MySQL',
      'sqlite': 'SQLite',
      'mongodb': 'MongoDB'
    };
    return typeMapping[databaseId] || databaseId;
  };

  // Only use API SQL connections, filtered by database type (exact, case-insensitive match)
  const getAllAvailableConnections = () => {
    const expectedDatabaseType = getDatabaseTypeFromId(database.id).toLowerCase();
    // Debug log to help diagnose API types
    console.log('API connection types:', sqlConnections.map(conn => conn.connection_database_type));
    return sqlConnections
      .filter(conn => {
        const apiType = (conn.connection_database_type || '').toLowerCase();
        // Only allow exact match
        return apiType === expectedDatabaseType;
      })
      .map(conn => ({
        value: `sql_${conn.connection_name}`,
        label: `${conn.connection_name}`,
        type: conn.connection_database_type,
        source: 'api'
      }));
  };

  // Handle generate query
  const handleGenerateQuery = async () => {
    if (!queryData.selectedConnection || !queryData.naturalLanguageQuery.trim()) {
      setQueryData(prev => ({
        ...prev,
        error: "Please select a connection and enter a natural language query"
      }));
      return;
    }

    setIsGenerating(true);
    setQueryData(prev => ({
      ...prev,
      error: null,
      showGeneratedQuery: false,
      showResult: false
    }));

    try {
      const databaseType = getSelectedDatabaseType();
      const result = await generateQuery(databaseType, queryData.naturalLanguageQuery);
      
      if (result.success) {
        setQueryData(prev => ({
          ...prev,
          generatedQuery: result.data.generated_query || result.data.query || '',
          showGeneratedQuery: true
        }));
      } else {
        setQueryData(prev => ({
          ...prev,
          error: result.error || "Failed to generate query"
        }));
      }
    } catch (error) {
      setQueryData(prev => ({
        ...prev,
        error: "Failed to generate query. Please try again."
      }));
    } finally {
      setIsGenerating(false);
    }
  };

  // Handle run query
  const handleRunQuery = async () => {
    if (!queryData.generatedQuery.trim()) {
      setQueryData(prev => ({
        ...prev,
        error: "No query to execute"
      }));
      return;
    }

    if (!queryData.selectedConnection) {
      setQueryData(prev => ({
        ...prev,
        error: "Please select a connection"
      }));
      return;
    }

    setQueryData(prev => ({
      ...prev,
      error: null,
      showResult: false,
      toastMessage: null,
      toastType: null
    }));

    try {
      if (onRunQuery) {
        await onRunQuery(queryData);
      }
      // Build payload with only required fields
      const selectedConnObj = getAllAvailableConnections().find(conn => conn.value === queryData.selectedConnection) || {};
      const payload = {
        connectionName: selectedConnObj.label || '',
        databaseType: selectedConnObj.type || 'SQLite',
        databaseName: selectedConnObj.databaseName || '',
        query: queryData.generatedQuery,
      };
      const result = await executeQuery(payload.connectionName, payload.query, payload);
      if (result.success) {
        setQueryData(prev => ({
          ...prev,
          queryResult: result.data,
          toastMessage: "Query executed successfully!",
          toastType: "success",
          showResult: true,
        }));
        setShowResponseModal(true);
      } else {
        setQueryData(prev => ({
          ...prev,
          error: result.error || "Failed to execute query",
          toastMessage: result.error || "Failed to execute query",
          toastType: "error"
        }));
      }
    } catch (error) {
      setQueryData(prev => ({
        ...prev,
        error: "Failed to execute query. Please try again.",
        toastMessage: "Failed to execute query. Please try again.",
        toastType: "error"
      }));
    }
  };

  const allConnections = getAllAvailableConnections();
  const hasConnections = allConnections.length > 0;
  const isLoadingConnections = loadingSqlConnections;

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        {isExecuting && <Loader />}
        <div className={styles.modalHeader}>
          <div className={styles.headerLeft}>
            <div
              className={styles.databaseIcon}
              style={{ backgroundColor: database.color }}
            >
              <SVGIcons
                icon={database.icon}
                width={24}
                height={24}
                fill="white"
              />
            </div>
            <div>
              <h3 className={styles.modalTitle}>Run Query - {database.name}</h3>
              <p className={styles.modalSubtitle}>Execute queries on your database</p>
            </div>
          </div>
          <button
            className={styles.closeButton}
            onClick={onClose}
            aria-label="Close modal"
          >
            <SVGIcons icon="close" width={24} height={24} fill="#666" />
          </button>
        </div>

        <div className={styles.modalBody}>
          
          <div className={styles.formGroup}>
            <label htmlFor="selectedConnection" className={styles.label}>
              Select Connection <span className={styles.required}>*</span>
            </label>
            <select
              id="selectedConnection"
              name="selectedConnection"
              value={queryData.selectedConnection}
              onChange={handleQueryInputChange}
              className={styles.select}
              disabled={isLoadingConnections || !hasConnections}
              required
            >
              <option value="">
                {isLoadingConnections ? "Loading connections..." : hasConnections ? "Select a connection..." : "No connections available"}
              </option>
              {allConnections.map((conn) => (
                <option key={conn.value} value={conn.value}>
                  {conn.label}
                </option>
              ))}
            </select>
          </div>

          <div className={styles.formGroup}>
            <label className={styles.label}>Selected DB Type:
              <span className={styles.dbTypeText}>{getSelectedDatabaseType() || 'No database selected'}</span>
            </label>
          </div>

          <div className={styles.formGroup}>
            <label htmlFor="naturalLanguageQuery" className={styles.label}>
              Enter Natural Language Query <span className={styles.required}>*</span>
            </label>
            <textarea
              id="naturalLanguageQuery"
              name="naturalLanguageQuery"
              value={queryData.naturalLanguageQuery}
              onChange={handleQueryInputChange}
              className={styles.textarea}
              rows="4"
              placeholder="e.g., Show me all users who registered last month"
              required
            />
          </div>

          <div className={styles.buttonGroup}>
            <button 
              type="button"
              onClick={handleGenerateQuery} 
              className={styles.generateButton}
              disabled={
                isGenerating ||
                !hasConnections ||
                !queryData.selectedConnection ||
                !queryData.naturalLanguageQuery.trim()
              }
            >
              Generate Query
            </button>
          </div>

          {queryData.showGeneratedQuery && (
            <div className={styles.generatedQueryContainer}>
              <div className={styles.formGroup}>
                <label htmlFor="generatedQuery" className={styles.label}>
                  Review or Edit the Generated Query
                </label>
                <textarea
                  id="generatedQuery"
                  name="generatedQuery"
                  value={queryData.generatedQuery}
                  onChange={handleQueryInputChange}
                  className={styles.textarea}
                  rows="8"
                />
              </div>
              
              <div className={styles.buttonGroup}>
                <button 
                  type="button"
                  onClick={handleRunQuery} 
                  className={styles.runButton}
                  disabled={isExecuting || !hasConnections}
                >
                  Run Query
                </button>
              </div>
            </div>
          )}


           {queryData.toastMessage && (
            <div
              className={`${styles.toastMessage} ${queryData.toastType === 'success' ? styles.toastSuccess : styles.toastError}`}
            >
              <span className={styles.toastIcon}>
                {queryData.toastType === 'success' ? '✔️' : '❌'}
              </span>
              <span>{queryData.toastMessage}</span>
            </div>
          )}

          {queryData.showResult && queryData.queryResult && (
            <div className={styles.resultContainer}>
              <h4>Query Result:</h4>
              {Array.isArray(queryData.queryResult?.rows) && queryData.queryResult.rows.length > 0 ? (
                <table className={styles.resultTable}>
                  <thead>
                    <tr>
                      <th>Row</th>
                      {queryData.queryResult.columns.map((col) => (
                        <th key={col}>{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {queryData.queryResult.rows.map((row, idx) => (
                      <tr key={idx}>
                        <td className={styles.rowIndex}>{idx + 1}</td>
                        {queryData.queryResult.columns.map((col, i) => (
                          <td key={i}>
                            {row[col]}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p>No data returned.</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default QueryModal;
