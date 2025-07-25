import React, { useState, useEffect } from "react";
import styles from "./CrudModal.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { fetchMongodbConnections } from "../../services/databaseService";
import Loader from "../commonComponents/Loader.jsx";
import { useMessage } from "../../Hooks/MessageContext";

const CrudModal = ({ database, onClose, onExecuteCrud, isExecuting }) => {
  const [crudData, setCrudData] = useState({
    selectedConnection: "",
    collection: "",
    operation: "",
    mode: "",
    jsonQuery: "",
    dataJson: "",
    updateJson: "",
    result: null,
    error: null,
    showResult: false
  });

  const [mongodbConnections, setMongodbConnections] = useState([]);
  const [loadingMongodbConnections, setLoadingMongodbConnections] = useState(false);
  const { setShowPopup } = useMessage();

  // Fetch MongoDB connections from API
  const fetchMongodbConnectionsData = async () => {
    setLoadingMongodbConnections(true);
    try {
      const result = await fetchMongodbConnections();
      if (result.success) {
        setMongodbConnections(result.data.connections || []);
      } else {
        setMongodbConnections([]);
      }
    } catch (error) {
      setMongodbConnections([]);
    } finally {
      setLoadingMongodbConnections(false);
    }
  };

  // Fetch MongoDB connections when component mounts
  useEffect(() => {
    fetchMongodbConnectionsData();
  }, []);

  useEffect(() => {
    if (!isExecuting) {
      setShowPopup(true);
    } else {
      setShowPopup(false);
    }
  }, [isExecuting, setShowPopup]);

  // Handle input changes
  const handleCrudInputChange = (e) => {
    const { name, value } = e.target;
    setCrudData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  // Handle execute CRUD operation
  const handleExecuteCrud = async () => {
    if (!crudData.selectedConnection || !crudData.collection || !crudData.operation || !crudData.mode) {
      setCrudData(prev => ({
        ...prev,
        error: "Please fill in all required fields"
      }));
      return;
    }

    if (!crudData.jsonQuery.trim()) {
      setCrudData(prev => ({
        ...prev,
        error: "Please enter a query"
      }));
      return;
    }

    // Validate JSON query
    try {
      JSON.parse(crudData.jsonQuery);
    } catch (error) {
      setCrudData(prev => ({
        ...prev,
        error: "Invalid JSON in query field"
      }));
      return;
    }

    // Validate dataJson for insert operation
    if (crudData.operation === "insert" && crudData.dataJson) {
      try {
        JSON.parse(crudData.dataJson);
      } catch (error) {
        setCrudData(prev => ({
          ...prev,
          error: "Invalid JSON in data field"
        }));
        return;
      }
    }

    // Validate updateJson for update operation
    if (crudData.operation === "update" && crudData.updateJson) {
      try {
        JSON.parse(crudData.updateJson);
      } catch (error) {
        setCrudData(prev => ({
          ...prev,
          error: "Invalid JSON in update field"
        }));
        return;
      }
    }

    setCrudData(prev => ({
      ...prev,
      error: null,
      showResult: false
    }));

    try {
      if (onExecuteCrud) {
        const result = await onExecuteCrud(crudData);
        setCrudData(prev => ({
          ...prev,
          result: result,
          showResult: true
        }));
      }
    } catch (error) {
      setCrudData(prev => ({
        ...prev,
        error: "Failed to execute CRUD operation. Please try again."
      }));
    }
  };

  // Get API MongoDB connections only
  const getAPIMongoDBConnections = () => {
    return mongodbConnections.map(conn => ({
      value: `mongodb_${conn.connection_name}`,
      label: `${conn.connection_name}`,
      source: 'api'
    }));
  };

  const allMongoDBConnections = getAPIMongoDBConnections();
  const hasConnections = allMongoDBConnections.length > 0;

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
              <h3 className={styles.modalTitle}>CRUD Operations - {database.name}</h3>
              <p className={styles.modalSubtitle}>Perform database operations</p>
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
              Select Connected DB <span className={styles.required}>*</span>
            </label>
            <select
              id="selectedConnection"
              name="selectedConnection"
              value={crudData.selectedConnection}
              onChange={handleCrudInputChange}
              className={styles.select}
              disabled={loadingMongodbConnections || !hasConnections}
              required
            >
              <option value="">
                {loadingMongodbConnections ? "Loading connections..." : hasConnections ? "Select a MongoDB connection..." : "No connections available"}
              </option>
              {allMongoDBConnections.map((conn) => (
                <option key={conn.value} value={conn.value}>
                  {conn.label}
                </option>
              ))}
            </select>
          </div>

          <div className={styles.formGroup}>
            <label htmlFor="collection" className={styles.label}>
              Collection <span className={styles.required}>*</span>
            </label>
            <input
              id="collection"
              name="collection"
              type="text"
              value={crudData.collection}
              onChange={handleCrudInputChange}
              className={styles.input}
              required
            />
          </div>

          <div className={styles.formGroup}>
            <label htmlFor="operation" className={styles.label}>
              Operation <span className={styles.required}>*</span>
            </label>
            <select
              id="operation"
              name="operation"
              value={crudData.operation}
              onChange={handleCrudInputChange}
              className={styles.select}
              required
            >
              <option value="">Select operation</option>
              <option value="find">Find</option>
              <option value="insert">Insert</option>
              <option value="delete">Delete</option>
              <option value="update">Update</option>
            </select>
          </div>

          <div className={styles.formGroup}>
            <label htmlFor="mode" className={styles.label}>
              Mode <span className={styles.required}>*</span>
            </label>
            <select
              id="mode"
              name="mode"
              value={crudData.mode}
              onChange={handleCrudInputChange}
              className={styles.select}
              required
            >
              <option value="">Select mode</option>
              <option value="one">One</option>
              <option value="many">Many</option>
            </select>
          </div>

          <div className={styles.formGroup}>
            <label htmlFor="jsonQuery" className={styles.label}>
              Query (JSON) <span className={styles.required}>*</span>
            </label>
            <textarea
              id="jsonQuery"
              name="jsonQuery"
              value={crudData.jsonQuery}
              onChange={handleCrudInputChange}
              className={styles.textarea}
              rows="8"
              required
            />
          </div>

          {/* Conditional Data JSON field for insert operation */}
          {crudData.operation === "insert" && (
            <div className={styles.formGroup}>
              <label htmlFor="dataJson" className={styles.label}>
                Data (JSON) <span className={styles.required}>*</span>
              </label>
              <textarea
                id="dataJson"
                name="dataJson"
                value={crudData.dataJson || ""}
                onChange={handleCrudInputChange}
                className={styles.textarea}
                rows="6"
                required
              />
            </div>
          )}

          {/* Conditional Update JSON field for update operation */}
          {crudData.operation === "update" && (
            <div className={styles.formGroup}>
              <label htmlFor="updateJson" className={styles.label}>
                Update (JSON) <span className={styles.required}>*</span>
              </label>
              <textarea
                id="updateJson"
                name="updateJson"
                value={crudData.updateJson || ""}
                onChange={handleCrudInputChange}
                className={styles.textarea}
                rows="6"
                required
              
              />
            </div>
          )}

          <div className={styles.buttonGroup}>
            <button 
              type="button"
              className={styles.executeButton}
              onClick={handleExecuteCrud}
              disabled={loadingMongodbConnections || !hasConnections || isExecuting}
            >
              Execute
            </button>
          </div>

          {crudData.error && (
            <div className={styles.errorMessage}>
              <p>Error: {crudData.error}</p>
            </div>
          )}

          {crudData.showResult && crudData.result && (
            <div className={styles.resultContainer}>
              <h4>Operation Result:</h4>
              <pre className={styles.result}>
                {JSON.stringify(crudData.result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CrudModal;
