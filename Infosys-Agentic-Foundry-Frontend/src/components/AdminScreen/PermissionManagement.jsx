import React, { useState } from "react";
import styles from "./AgentAssignment.module.css";

const PermissionManagement = () => {
  // State to manage all permissions
  const [permissions, setPermissions] = useState({
    Tools: {
      read: false,
      create: false,
      update: false,
      delete: false,
      execute_access: false
    },
    agents: {
      create: false,
      update: false,
      read: false,
      delete: false,
      execute_access: false
    },
    chat: {
      execution_steps_access: false,
      tool_verifier_flag_access: false,
      plan_verifier_flag_access: false,
      evaluation: false
    },
    vault: {
      vault_access: false
    },
    "Data Connectors": {
      data_connector_access: false
    }
  });

  // Handle toggle changes
  const handleToggleChange = (category, permission) => {
    setPermissions(prev => ({
      ...prev,
      [category]: {
        ...prev[category],
        [permission]: !prev[category][permission]
      }
    }));
  };

  // Render toggle switch
  const renderToggle = (category, permission, label) => {
    const isChecked = permissions[category][permission];
    return (
      <div key={permission} className={styles.permissionItem}>
        <label className={styles.permissionLabel}>
          <span className={styles.permissionText}>{label}</span>
          <div className={styles.toggleContainer}>
            <input
              type="checkbox"
              checked={isChecked}
              onChange={() => handleToggleChange(category, permission)}
              className={styles.toggleInput}
            />
            <span className={`${styles.toggleSlider} ${isChecked ? styles.toggleActive : ''}`}></span>
          </div>
        </label>
      </div>
    );
  };

  // Render permission category
  const renderCategory = (categoryName, categoryPermissions) => {
    return (
      <div key={categoryName} className={styles.permissionCategory}>
        <h3 className={styles.categoryTitle}>{categoryName}</h3>
        <div className={styles.permissionsList}>
          {Object.keys(categoryPermissions).map(permission => 
            renderToggle(categoryName, permission, permission.replace(/_/g, ' '))
          )}
        </div>
      </div>
    );
  };

  return (
    <div className={styles.permissionsContainer}>
      <div className={styles.permissionsHeader}>
        <h2>Permission Management</h2>
        <p>Configure access permissions for different system components</p>
      </div>
      
      <div className={styles.permissionsContent}>
        {Object.keys(permissions).map(category => 
          renderCategory(category, permissions[category])
        )}
      </div>
      
      <div className={styles.permissionsActions}>
        <button className={styles.saveButton} type="button">
          Save Permissions
        </button>
        <button className={styles.resetButton} type="button">
          Reset to Default
        </button>
      </div>
    </div>
  );
};

export default PermissionManagement;