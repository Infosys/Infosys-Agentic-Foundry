import React, { useState, useEffect } from "react";
import styles from "./CrudModal.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { useDatabases } from "./service/databaseService.js";
import Loader from "../commonComponents/Loader.jsx";
import { useMessage } from "../../Hooks/MessageContext";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button.jsx";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import { Modal } from "../commonComponents/Modal";
import { sanitizeInput } from "../../utils/sanitization";

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
    showResult: false,
  });

  const [mongodbConnections, setMongodbConnections] = useState([]);
  const [loadingMongodbConnections, setLoadingMongodbConnections] = useState(false);
  const { setShowPopup } = useMessage();
  const { fetchMongodbConnections } = useDatabases();

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

  // Handle input changes - JSON/database fields retain special characters for valid operations
  // XSS protection: React auto-escapes output; values sent to API, not rendered as raw HTML
  const handleCrudInputChange = (e) => {
    const { name, value } = e.target;
    // Sanitize collection name (text field) while preserving JSON content
    const sanitizedValue = name === "collection" ? sanitizeInput(value, "text") : value;
    setCrudData((prev) => {
      // If any field is changed after result is shown, reset result and showResult
      if (prev.showResult) {
        return {
          ...prev,
          [name]: sanitizedValue,
          result: null,
          showResult: false,
          error: null, // Reset error when input changes
        };
      }
      // If user alters any JSON fields, reset result and showResult
      if (["jsonQuery", "dataJson", "updateJson"].includes(name)) {
        return {
          ...prev,
          [name]: sanitizedValue,
          result: null,
          showResult: false,
          error: null, // Reset error when input changes
        };
      }
      return {
        ...prev,
        [name]: sanitizedValue,
      };
    });
  };

  // Handle execute CRUD operation
  const handleExecuteCrud = async () => {
    if (!crudData.selectedConnection || !crudData.collection || !crudData.operation || !crudData.mode) {
      setCrudData((prev) => ({
        ...prev,
        error: "Please fill in all required fields",
      }));
      return;
    }

    if (!crudData.jsonQuery.trim()) {
      setCrudData((prev) => ({
        ...prev,
        error: "Please enter a query",
      }));
      return;
    }

    // Validate JSON query
    try {
      JSON.parse(crudData.jsonQuery);
    } catch (error) {
      setCrudData((prev) => ({
        ...prev,
        error: "Invalid JSON in query field",
      }));
      return;
    }

    // Validate dataJson for insert operation
    if (crudData.operation === "insert" && crudData.dataJson) {
      try {
        JSON.parse(crudData.dataJson);
      } catch (error) {
        setCrudData((prev) => ({
          ...prev,
          error: "Invalid JSON in data field",
        }));
        return;
      }
    }

    // Validate updateJson for update operation
    if (crudData.operation === "update" && crudData.updateJson) {
      try {
        JSON.parse(crudData.updateJson);
      } catch (error) {
        setCrudData((prev) => ({
          ...prev,
          error: "Invalid JSON in update field",
        }));
        return;
      }
    }

    setCrudData((prev) => ({
      ...prev,
      error: null,
      showResult: false,
    }));

    try {
      if (onExecuteCrud) {
        const result = await onExecuteCrud(crudData);
        setCrudData((prev) => ({
          ...prev,
          result: result,
          showResult: true,
        }));
      }
    } catch (error) {
      setCrudData((prev) => ({
        ...prev,
        error: "Failed to execute CRUD operation. Please try again.",
      }));
    }
  };

  // Get API MongoDB connections only
  const getAPIMongoDBConnections = () => {
    return mongodbConnections.map((conn) => ({
      value: `mongodb_${conn.connection_name}`,
      label: `${conn.connection_name}`,
      source: "api",
    }));
  };

  const allMongoDBConnections = getAPIMongoDBConnections();
  const hasConnections = allMongoDBConnections.length > 0;

  // Validation for required fields
  const isCrudFormValid = () => {
    return crudData.selectedConnection && crudData.collection && crudData.operation && crudData.mode;
  };

  return (
    <Modal
      isOpen={true}
      onClose={onClose}
      size="lg"
      ariaLabel={`CRUD Operations - ${database.name}`}
      className={styles.crudModal}
      showCloseButton={false}
    >
      {isExecuting && <Loader />}
      <div className={styles.modalHeader}>
        <div className={styles.headerLeft}>
          <div className={styles.databaseIcon} style={{ backgroundColor: database.color }}>
            <SVGIcons icon={database.icon} width={24} height={24} fill="white" />
          </div>
          <div>
            <h3 className={styles.modalTitle}>CRUD Operations - {database.name}</h3>
            <p className={styles.modalSubtitle}>Perform database operations</p>
          </div>
        </div>
        <button className="closeBtn" aria-label="Close modal" onClick={onClose}>
          ×
        </button>
      </div>

      <div className={styles.modalBody}>
        <div className="formGroup">
          <label htmlFor="selectedConnection" className="label-desc">
            Select Connected DB <span className="required">*</span>
          </label>
          <NewCommonDropdown
            options={allMongoDBConnections.map((conn) => conn.label)}
            selected={allMongoDBConnections.find((c) => c.value === crudData.selectedConnection)?.label || ""}
            onSelect={(label) => {
              const conn = allMongoDBConnections.find((c) => c.label === label);
              if (conn) {
                handleCrudInputChange({ target: { name: "selectedConnection", value: conn.value } });
              }
            }}
            placeholder={loadingMongodbConnections ? "Loading Connections..." : hasConnections ? "Select A MongoDB Connection..." : "No Connections Available"}
            showSearch={true}
            width="100%"
          />
        </div>

        <div className="formGroup">
          <label htmlFor="collection" className="label-desc">
            Collection <span className="required">*</span>
          </label>
          <input id="collection" name="collection" type="text" value={crudData.collection} onChange={handleCrudInputChange} className="input" required />
        </div>

        <div className="formGroup">
          <label htmlFor="operation" className="label-desc">
            Operation <span className="required">*</span>
          </label>
          <NewCommonDropdown
            options={["Find", "Insert", "Delete", "Update"]}
            selected={crudData.operation ? crudData.operation.charAt(0).toUpperCase() + crudData.operation.slice(1) : ""}
            onSelect={(value) => {
              handleCrudInputChange({ target: { name: "operation", value: value.toLowerCase() } });
            }}
            placeholder="Select Operation"
            showSearch={false}
            width="100%"
          />
        </div>

        <div className="formGroup">
          <label htmlFor="mode" className="label-desc">
            Mode <span className="required">*</span>
          </label>
          <NewCommonDropdown
            options={crudData.operation !== "insert" ? ["One", "Many"] : ["One"]}
            selected={crudData.mode ? crudData.mode.charAt(0).toUpperCase() + crudData.mode.slice(1) : ""}
            onSelect={(value) => {
              handleCrudInputChange({ target: { name: "mode", value: value.toLowerCase() } });
            }}
            placeholder="Select Mode"
            showSearch={false}
            width="100%"
          />
        </div>

        <div className="formGroup">
          <label htmlFor="jsonQuery" className="label-desc">
            Query (JSON)
          </label>
          <textarea id="jsonQuery" name="jsonQuery" value={crudData.jsonQuery} onChange={handleCrudInputChange} className="textarea" rows="8" />
        </div>

        {/* Conditional Data JSON field for insert operation */}
        {crudData.operation === "insert" && (
          <div className="formGroup">
            <label htmlFor="dataJson" className="label-desc">
              Data (JSON)
            </label>
            <textarea id="dataJson" name="dataJson" value={crudData.dataJson || ""} onChange={handleCrudInputChange} className="textarea" rows="6" />
          </div>
        )}

        {/* Conditional Update JSON field for update operation */}
        {crudData.operation === "update" && (
          <div className="formGroup">
            <label htmlFor="updateJson" className="label-desc">
              Update (JSON)
            </label>
            <textarea id="updateJson" name="updateJson" value={crudData.updateJson || ""} onChange={handleCrudInputChange} className="textarea" rows="6" />
          </div>
        )}

        <div className={styles.buttonGroup}>
          <IAFButton type="secondary" onClick={onClose}>
            Cancel
          </IAFButton>
          <IAFButton type="primary" onClick={handleExecuteCrud} disabled={loadingMongodbConnections || !hasConnections || isExecuting || !isCrudFormValid()}>
            Execute
          </IAFButton>
        </div>

        {crudData.error && (
          <div className={styles.errorMessage}>
            <p>Error: {crudData.error}</p>
          </div>
        )}

        {crudData.showResult && crudData.result && (
          <div className={styles.resultContainer}>
            <h4>Operation Result:</h4>
            <pre className={styles.result}>{JSON.stringify(crudData.result, null, 2)}</pre>
          </div>
        )}
      </div>
    </Modal>
  );
};

export default CrudModal;
