import React, { useState, useEffect } from "react";
import styles from "./ConnectionModal.module.css";
import groundTruthStyles from "../GroundTruth/GroundTruth.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { useMessage } from "../../Hooks/MessageContext";
import Loader from "../commonComponents/Loader.jsx";

const ConnectionModal = ({ database, onClose, onSubmit, isConnecting }) => {
  const [formData, setFormData] = useState({});
  const [showPassword, setShowPassword] = useState(false);
  const { addMessage } = useMessage();
  const [loading, setLoading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  // Initialize form data based on database fields
  useEffect(() => {
    const initialData = {};
    database.fields.forEach(field => {
      // Set default values for readonly fields
      initialData[field.name] = field.defaultValue || '';
    });
    setFormData(initialData);
  }, [database]);

  // Field-specific input restrictions for each field
  const getSanitizedValue = (name, value) => {
    switch (name) {
      case 'connectionName':
        // return value.replace(/[^a-zA-Z0-9_\s()\-\[\]{}]/g, ""); // Remove all escapes for [ and ]
        return value.replace(/[^a-zA-Z0-9_\s()-{}[\]]/g, "");
      case 'host':
        return value.replace(/[^a-zA-Z0-9.-]/g, "");
      case 'port':
        return value.replace(/[^0-9]/g, "");
      case 'username':
        return value.replace(/[^a-zA-Z]/g, "");
      case 'password':
        return value.replace(/[^a-zA-Z0-9]/g, "");
      case 'databaseName':
       return value.replace(/[^a-zA-Z0-9]/g, "");
      default:
        return value;
    }
  };

  const handleInputChange = (e) => {
    const { name } = e.target;
    let value = getSanitizedValue(name, e.target.value);
    setFormData(prev => ({
      ...prev,
      [name]: value,
      // If user types in databaseName, clear uploaded_file
      ...(isSqlite && name === 'databaseName' && value ? { uploaded_file: null } : {})
    }));
  };

  const handleFileInputChange = (e) => {
    const file = e.target.files[0];
    if (file && validateFile(file)) {
      setFormData(prev => ({
        ...prev,
        uploaded_file: file,
        // If user uploads file, clear databaseName
        ...(isSqlite ? { databaseName: '' } : {})
      }));
      setSuccessMessage("File uploaded successfully.");
    }
    e.target.value = '';
  };

  const handleRemoveFile = () => {
    setFormData(prev => ({ ...prev, uploaded_file: null }));
    setSuccessMessage(""); // Clear the success message when file is removed
    const fileInput = document.getElementById('sqlite_uploaded_file');
    if (fileInput) fileInput.value = '';
  };

  const handleDragEnter = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isDragging) setIsDragging(true);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      if (validateFile(file)) {
        setFormData(prev => ({ ...prev, uploaded_file: file }));
        setSuccessMessage("File uploaded successfully.");
      }
    }
  };

  const validateFile = (file) => {
    if (!file) return false;
    const validExtensions = ['.db', '.sqlite', '.sqlite3'];
    const fileName = file.name.toLowerCase();
    const isValidExtension = validExtensions.some(ext => fileName.endsWith(ext));
    if (!isValidExtension) {
      setErrorMessage("Invalid file format. Please upload a .db, .sqlite, or .sqlite3 file.");
      return false;
    }
    const maxSize = 200 * 1024 * 1024; // 200MB
    if (file.size > maxSize) {
      setErrorMessage('File size exceeds 200MB limit.');
      return false;
    }
    setErrorMessage("");
    return true;
  };

  // Helper: check if either path or file is filled for SQLite
  const isSqlite = database.id === 'sqlite';
  const hasDbPath = isSqlite && formData.databaseName && formData.databaseName.trim() !== '';
  const hasDbFile = isSqlite && formData.uploaded_file;

  const handleSubmit = async (e) => {
    e.preventDefault();
    // Defensive: For SQLite, only validate one of the two: path or file
    let requiredFields;
    if (isSqlite) {
      if (!hasDbPath && !hasDbFile) {
        addMessage('Please provide either a filename or upload a file for SQLite.', 'error');
        return;
      }
      if (hasDbPath && hasDbFile) {
        addMessage('Please provide only one: filename or file upload for SQLite.', 'error');
        return;
      }
      // Only require connectionName and databaseType for SQLite
      requiredFields = database.fields.filter(field => ['connectionName', 'databaseType'].includes(field.name));
      const missingFields = requiredFields.filter(field => !formData[field.name]);
      if (missingFields.length > 0) {
        addMessage(`Please fill in required fields: ${missingFields.map(f => f.label).join(', ')}`, "error");
        return;
      }
    } else {
      requiredFields = database.fields.filter(field => field.required);
      const missingFields = requiredFields.filter(field => !formData[field.name]);
      if (missingFields.length > 0) {
        addMessage(`Please fill in required fields: ${missingFields.map(f => f.label).join(', ')}`, "error");
        return;
      }
    }
    setLoading(true);
    // Create a synthetic event object that mimics the form submission
    const syntheticEvent = {
      preventDefault: () => {},
      target: {
        elements: Object.keys(formData).reduce((acc, key) => {
          acc[key] = { value: formData[key] };
          return acc;
        }, {})
      }
    };

    // Call the passed onSubmit function with the form data
    if (onSubmit) {
      let connectionData = {
        connectionName: formData.connectionName,
        databaseType: formData.databaseType,
        host: '',
        port: '',
        username: '',
        password: '',
        // For SQLite, only include the selected one
        ...(isSqlite && hasDbPath ? { databaseName: formData.databaseName } : {}),
        ...(isSqlite && hasDbFile ? { uploaded_file: formData.uploaded_file } : {}),
      };
      if (formData.databaseType.toLowerCase() !== 'sqlite') {
        connectionData.host = formData.host;
        connectionData.port = formData.port;
        connectionData.username = formData.username;
        connectionData.password = formData.password;
        connectionData.databaseName = formData.databaseName;
      }
      window.tempConnectionData = connectionData;
      try {
        await onSubmit(syntheticEvent);
        setLoading(false);
        onClose(); // Close modal on success
      } catch (error) {
        setLoading(false);
      }
    }
  };

  const togglePasswordVisibility = () => {
    setShowPassword(!showPassword);
  };

  // Helper: check if all required fields are filled and displayed
  const areAllRequiredFieldsFilled = (() => {
    if (isSqlite) {
      // For SQLite, require either databaseName or uploaded_file, not both, and required fields
      if (!hasDbPath && !hasDbFile) return false;
      if (hasDbPath && hasDbFile) return false;
      // Only require connectionName and databaseType for SQLite
      const requiredFields = database.fields.filter(field => ['connectionName', 'databaseType'].includes(field.name));
      return requiredFields.every(field => formData[field.name]);
    } else {
      const requiredFields = database.fields.filter(field => field.required);
      return requiredFields.every(field => formData[field.name]);
    }
  })();

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <div className={styles.modalTitle}>
            <div 
              className={styles.modalIcon}
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
              <h2>Connect to {database.name}</h2>
              <p>{database.description}</p>
            </div>
          </div>
          <button 
            className={styles.closeButton}
            onClick={onClose}
            type="button"
          >
            <SVGIcons icon="close" width={24} height={24} fill="#666" />
          </button>
        </div>

        <form className={styles.form} onSubmit={handleSubmit}>
          {loading && (
            <Loader />
            )}
          <div className={styles.formBody}>
            {database.fields.map((field, index) => (
              <div key={field.name} className={styles.formGroup}>
                <label htmlFor={field.name} className={styles.label}>
                  {field.label}
                  {field.required && <span className={styles.required}>*</span>}
                </label>
                
                {field.type === 'password' ? (
                  <div className={styles.passwordContainer}>
                    <input
                      id={field.name}
                      name={field.name}
                      type={showPassword ? 'text' : 'password'}
                      value={formData[field.name] || ''}
                      onChange={handleInputChange}
                      className={styles.input}
                      required={field.required}
                    />
                    <button
                      type="button"
                      className={styles.passwordToggle}
                      onClick={togglePasswordVisibility}
                    >
                      <SVGIcons
                        icon={showPassword ? "eye-slash" : "eye"}
                        width={20}
                        height={20}
                        fill="#666"
                      />
                    </button>
                  </div>
                ) : field.name === 'databaseName' && database.id === 'sqlite' ? (
                  <input
                    id={field.name}
                    name={field.name}
                    type={field.type}
                    value={formData[field.name] || ''}
                    onChange={handleInputChange}
                    className={styles.input}
                    required={field.required}
                    readOnly={field.readOnly}
                    disabled={!!formData.uploaded_file}
                  />
                ) : (
                  <input
                    id={field.name}
                    name={field.name}
                    type={field.type}
                    value={formData[field.name] || ''}
                    onChange={handleInputChange}
                    className={styles.input}
                    required={field.required}
                    readOnly={field.readOnly}
                  />
                )}
              </div>
            ))}
            {database.id === 'sqlite' && (
            <div className={styles.warningMessage}>
                  Please upload a file or enter a new file name.
                </div>)}
            {/* SQLite Upload File Field */}
            {database.id === 'sqlite' && (
              <div className={groundTruthStyles.formGroup}>
                <div className={groundTruthStyles.labelWithInfo}>
                  <label htmlFor="sqlite_uploaded_file" className={groundTruthStyles.label}>
                    Upload File
                  </label>
                </div>
                <input
                  type="file"
                  id="sqlite_uploaded_file"
                  name="uploaded_file"
                  onChange={handleFileInputChange}
                  className={groundTruthStyles.fileInput}
                  accept=".db,.sqlite,.sqlite3"
                  style={{ display: 'none' }}
                />
                {!formData.uploaded_file ? (
                  <div
                    className={`${groundTruthStyles.fileUploadContainer} ${isDragging ? groundTruthStyles.dragging : ''}`}
                    onDragEnter={handleDragEnter}
                    onDragLeave={handleDragLeave}
                    onDragOver={handleDragOver}
                    onDrop={hasDbPath ? undefined : handleDrop}
                    onClick={() => !hasDbPath && document.getElementById('sqlite_uploaded_file').click()}
                    style={{ pointerEvents: hasDbPath ? 'none' : 'auto', opacity: hasDbPath ? 0.5 : 1 }}
                  >
                    <div className={groundTruthStyles.uploadPrompt}>
                      <span>{isDragging ? "Drop file here" : "Click to upload or drag and drop"}</span>
                      <span><small>Supported Extensions db, sqlite, sqlite3</small></span>
                    </div>
                  </div>
                ) : (
                  <div className={groundTruthStyles.fileCard}>
                    <div className={groundTruthStyles.fileInfo}>
                      <span className={groundTruthStyles.fileName}> {formData.uploaded_file.name}</span>
                      <button
                        type="button"
                        onClick={handleRemoveFile}
                        className={groundTruthStyles.removeFileButton}
                        aria-label="Remove file"
                      >&times;</button>
                    </div>
                  </div>
                )}
                {errorMessage && (
                  <div className={styles.errorMessage}>{errorMessage}</div>
                )}
                {successMessage && !errorMessage && (
                  <div className={styles.successMessage}>{successMessage}</div>
                )}
              </div>
            )}
          </div>

          <div className={styles.modalFooter}>
            <button
              type="button"
              className={styles.cancelButton}
              onClick={onClose}
              disabled={isConnecting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className={styles.connectButton}
              disabled={isConnecting || !areAllRequiredFieldsFilled}
            >
                  <SVGIcons icon="plug" width={16} height={16} fill="white" />
                    Connect
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default ConnectionModal;
