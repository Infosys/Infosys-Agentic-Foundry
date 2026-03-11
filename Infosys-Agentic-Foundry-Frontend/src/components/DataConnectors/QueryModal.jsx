import React, { useState, useEffect, useRef } from "react";
import styles from "./QueryModal.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { useDatabases } from "./service/databaseService.js";
import Loader from "../commonComponents/Loader.jsx";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button.jsx";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import { Modal } from "../commonComponents/Modal";
import { sanitizeInput } from "../../utils/sanitization";

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
  const [isQueryEdited, setIsQueryEdited] = useState(false);
  const { fetchSqlConnections, generateQuery, executeQuery } = useDatabases();
  const hasSqlConnectionsRef = useRef(false);
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
    if (!hasSqlConnectionsRef.current) {
      hasSqlConnectionsRef.current = true;
      fetchSqlConnectionsData();
    }
  }, []);

  // Handle input changes with sanitization for text inputs
  const handleQueryInputChange = (e) => {
    const { name, value } = e.target;
    // Sanitize natural language query to prevent XSS
    const sanitizedValue = name === "naturalLanguageQuery" ? sanitizeInput(value, "text") : value;
    setQueryData((prev) => {
      // If user clears the natural language input or changes connection, hide generated query/results and reset errors/toasts
      if ((name === "naturalLanguageQuery" && sanitizedValue.trim() === "") || (name === "selectedConnection" && sanitizedValue === "")) {
        setIsQueryEdited(false);
        return {
          ...prev,
          [name]: sanitizedValue,
          generatedQuery: "",
          showGeneratedQuery: false,
          showResult: false,
          queryResult: null,
          error: null,
          toastMessage: null,
          toastType: null,
        };
      }
      // If user edits the natural language query (not just clears), hide generated query/results
      if (name === "naturalLanguageQuery") {
        setIsQueryEdited(false);
        return {
          ...prev,
          [name]: sanitizedValue,
          showGeneratedQuery: false,
          showResult: false,
          error: null,
          toastMessage: null,
          toastType: null,
        };
      }
      // If user edits the generated query, disable run button and reset result
      if (name === "generatedQuery") {
        setIsQueryEdited(true);
        return {
          ...prev,
          [name]: sanitizedValue,
          showResult: false,
          queryResult: null,
          error: null,
          toastMessage: null,
          toastType: null,
        };
      }
      return {
        ...prev,
        [name]: sanitizedValue,
        error: null,
        toastMessage: null,
        toastType: null,
      };
    });
  };

  // Get selected database type
  const getSelectedDatabaseType = () => {
    const allConnections = getAllAvailableConnections();
    const selectedConn = allConnections.find((conn) => conn.value === queryData.selectedConnection);
    return selectedConn ? selectedConn.type : "";
  };

  // Map database ID to database type for filtering
  const getDatabaseTypeFromId = (databaseId) => {
    const typeMapping = {
      postgresql: "PostgreSQL",
      mysql: "MySQL",
      sqlite: "SQLite",
      mongodb: "MongoDB",
    };
    return typeMapping[databaseId] || databaseId;
  };

  // Only use API SQL connections, filtered by database type (exact, case-insensitive match)
  const getAllAvailableConnections = () => {
    const expectedDatabaseType = getDatabaseTypeFromId(database.id).toLowerCase();
    return sqlConnections
      .filter((conn) => {
        const apiType = (conn.connection_database_type || "").toLowerCase();
        // Only allow exact match
        return apiType === expectedDatabaseType;
      })
      .map((conn) => ({
        value: `sql_${conn.connection_name}`,
        label: `${conn.connection_name}`,
        type: conn.connection_database_type,
        source: "api",
      }));
  };

  // Handle generate query
  const handleGenerateQuery = async () => {
    if (!queryData.selectedConnection || !queryData.naturalLanguageQuery.trim()) {
      setQueryData((prev) => ({
        ...prev,
        error: "Please select a connection and enter a natural language query",
      }));
      return;
    }

    setIsGenerating(true);
    setQueryData((prev) => ({
      ...prev,
      error: null,
      showGeneratedQuery: false,
      showResult: false,
    }));

    try {
      const databaseType = getSelectedDatabaseType();
      const result = await generateQuery(databaseType, queryData.naturalLanguageQuery);

      if (result.success) {
        setQueryData((prev) => ({
          ...prev,
          generatedQuery: result.data.generated_query || result.data.query || "",
          showGeneratedQuery: true,
        }));
        setIsQueryEdited(false);
      } else {
        setQueryData((prev) => ({
          ...prev,
          error: result.error || "Failed to generate query",
        }));
      }
    } catch (error) {
      setQueryData((prev) => ({
        ...prev,
        error: "Failed to generate query. Please try again.",
      }));
    } finally {
      setIsGenerating(false);
    }
  };

  // Handle run query
  const handleRunQuery = async () => {
    if (!queryData.generatedQuery.trim()) {
      setQueryData((prev) => ({
        ...prev,
        error: "No query to execute",
      }));
      return;
    }

    if (!queryData.selectedConnection) {
      setQueryData((prev) => ({
        ...prev,
        error: "Please select a connection",
      }));
      return;
    }

    setQueryData((prev) => ({
      ...prev,
      error: null,
      showResult: false,
      toastMessage: null,
      toastType: null,
    }));

    try {
      if (onRunQuery) {
        await onRunQuery(queryData);
      }
      // Build payload with only required fields
      const selectedConnObj = getAllAvailableConnections().find((conn) => conn.value === queryData.selectedConnection) || {};
      const payload = {
        connectionName: selectedConnObj.label || "",
        databaseType: selectedConnObj.type || "SQLite",
        databaseName: selectedConnObj.databaseName || "",
        query: queryData.generatedQuery,
      };
      const result = await executeQuery(payload.connectionName, payload.query, payload);
      if (result.success) {
        setQueryData((prev) => ({
          ...prev,
          queryResult: result.data,
          toastMessage: "Query executed successfully!",
          toastType: "success",
          showResult: true,
        }));
      } else {
        setQueryData((prev) => ({
          ...prev,
          error: result.error || "Failed to execute query",
          toastMessage: result.error || "Failed to execute query",
          toastType: "error",
        }));
      }
    } catch (error) {
      setQueryData((prev) => ({
        ...prev,
        error: "Failed to execute query. Please try again.",
        toastMessage: "Failed to execute query. Please try again.",
        toastType: "error",
      }));
    }
  };

  // When generatedQuery is changed, check if it matches the original generated query to enable Run button
  useEffect(() => {
    if (queryData.showGeneratedQuery) {
      // Enable Run button only if generatedQuery is not empty and not edited
      setIsQueryEdited(queryData.generatedQuery !== "" && queryData.generatedQuery !== (queryData.generatedQuery || ""));
    } else {
      setIsQueryEdited(false);
    }
  }, [queryData.generatedQuery, queryData.showGeneratedQuery]);

  const allConnections = getAllAvailableConnections();
  const hasConnections = allConnections.length > 0;
  const isLoadingConnections = loadingSqlConnections;

  return (
    <Modal
      isOpen={true}
      onClose={onClose}
      size="lg"
      ariaLabel={`Run Query - ${database.name}`}
      className={styles.queryModal}
      showCloseButton={false}
    >
      {(isExecuting || isGenerating) && <Loader />}
      <div className={styles.modalHeader}>
        <div className={styles.headerLeft}>
          <div className={styles.databaseIcon} style={{ backgroundColor: database.color }}>
            <SVGIcons icon={database.icon} width={24} height={24} fill="white" />
          </div>
          <div>
            <h3 className={styles.modalTitle}>Run Query - {database.name}</h3>
            <p className={styles.modalSubtitle}>Execute queries on your database</p>
          </div>
        </div>
        <button className="closeBtn" onClick={onClose} aria-label="Close modal">
          ×
        </button>
      </div>

      <div className={styles.modalBody}>
        <div className="formGroup">
          <label htmlFor="selectedConnection" className="label-desc">
            Select Connection <span className="required">*</span>
          </label>
          <NewCommonDropdown
            options={allConnections.map((conn) => conn.label)}
            selected={allConnections.find((c) => c.value === queryData.selectedConnection)?.label || ""}
            onSelect={(label) => {
              const conn = allConnections.find((c) => c.label === label);
              if (conn) {
                handleQueryInputChange({ target: { name: "selectedConnection", value: conn.value } });
              }
            }}
            placeholder={isLoadingConnections ? "Loading Connections..." : hasConnections ? "Select A Connection..." : "No Connections Available"}
            showSearch={true}
            width="100%"
          />
        </div>

        <div className="formGroup">
          <label htmlFor="naturalLanguageQuery" className="label-desc">
            Enter Natural Language Query <span className="required">*</span>
          </label>
          <textarea
            id="naturalLanguageQuery"
            name="naturalLanguageQuery"
            value={queryData.naturalLanguageQuery}
            onChange={handleQueryInputChange}
            className="textarea"
            rows="4"
            placeholder="E.g., Show Me All Users Who Registered Last Month"
            required
          />
        </div>

        <div className={styles.buttonGroup}>
          <IAFButton type="secondary" onClick={onClose}>
            Cancel
          </IAFButton>
          <IAFButton
            type="primary"
            onClick={handleGenerateQuery}
            disabled={isGenerating || !hasConnections || !queryData.selectedConnection || !queryData.naturalLanguageQuery.trim()}>
            Generate Query
          </IAFButton>
        </div>

        {queryData.showGeneratedQuery && (
          <div className={styles.generatedQueryContainer}>
            <div className="formGroup">
              <label htmlFor="generatedQuery" className="label-desc">
                Review or Edit the Generated Query
              </label>
              <textarea id="generatedQuery" name="generatedQuery" value={queryData.generatedQuery} onChange={handleQueryInputChange} className="textarea" rows="8" />
            </div>

            <div className={styles.buttonGroup}>
              <IAFButton type="secondary" onClick={onClose}>
                Cancel
              </IAFButton>
              <IAFButton type="primary" onClick={handleRunQuery} disabled={isExecuting || !hasConnections || isQueryEdited || !queryData.generatedQuery.trim()}>
                Run Query
              </IAFButton>
            </div>
          </div>
        )}

        {queryData.toastMessage && (
          <div className={`${styles.toastMessage} ${queryData.toastType === "success" ? styles.toastSuccess : styles.toastError}`}>
            <span className={styles.toastIcon}>{queryData.toastType === "success" ? "✔️" : "❌"}</span>
            <span>{queryData.toastMessage}</span>
          </div>
        )}

        {queryData?.showResult && queryData.queryResult && Array.isArray(queryData.queryResult?.rows) && queryData.queryResult.rows.length > 0 && (
          <div className={styles.resultContainer}>
            <h4>Query Result:</h4>
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
                      <td key={i}>{row[col]}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Modal>
  );
};

export default QueryModal;
