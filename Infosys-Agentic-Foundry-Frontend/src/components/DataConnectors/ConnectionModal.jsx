import React, { useState, useEffect } from "react";
import styles from "./ConnectionModal.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { useMessage } from "../../Hooks/MessageContext";
import Loader from "../commonComponents/Loader.jsx";

const ConnectionModal = ({ database, onClose, onSubmit, isConnecting }) => {
  const [formData, setFormData] = useState({});
  const [showPassword, setShowPassword] = useState(false);
  const { addMessage } = useMessage();
   const [loading, setLoading] = useState(false);

  // Initialize form data based on database fields
  React.useEffect(() => {
    const initialData = {};
    database.fields.forEach(field => {
      // Set default values for readonly fields
      initialData[field.name] = field.defaultValue || '';
    });
    setFormData(initialData);
  }, [database]);

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    // Validate required fields
    const requiredFields = database.fields.filter(field => field.required);
    const missingFields = requiredFields.filter(field => !formData[field.name]);
    
    if (missingFields.length > 0) {
      addMessage(`Please fill in required fields: ${missingFields.map(f => f.label).join(', ')}`, "error");
      return;
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
      // We need to set the form data in a way that the hook can access it
      // This is a bit of a workaround since we're not using the hook's state directly
      const connectionData = {
        connectionName: formData.connectionName,
        databaseType: formData.databaseType,
        host: formData.host,
        port: formData.port,
        username: formData.username,
        password: formData.password,
        databaseName: formData.databaseName
      };
      
      // Store the connection data temporarily in a way the hook can access it
      window.tempConnectionData = connectionData;
      
      try {
        await onSubmit(syntheticEvent);
        setLoading(false);
        onClose(); // Close modal on success
      } catch (error) {
        setLoading(false);
        // Error handling is done in the hook
      }
    }
  };

  const togglePasswordVisibility = () => {
    setShowPassword(!showPassword);
  };

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
              disabled={isConnecting}
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
