import React, { useState } from "react";
import styles from "./AgentAssignment.module.css";

const RolePermissions = () => {
  // State to manage all permissions organized by categories
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

  // Render toggle switch component
  const renderToggle = (category, permission, label) => {
    const isChecked = permissions[category][permission];
    return (
      <div key={permission} className={styles.permissionToggleItem}>
        <label className={styles.permissionToggleLabel}>
          <span className={styles.permissionToggleText}>{label}</span>
          <div className={styles.toggleSwitchContainer}>
            <input
              type="checkbox"
              checked={isChecked}
              onChange={() => handleToggleChange(category, permission)}
              className={styles.toggleSwitchInput}
            />
            <span className={`${styles.toggleSwitchSlider} ${isChecked ? styles.toggleSwitchActive : ''}`}>
              <span className={styles.toggleSwitchCircle}></span>
            </span>
          </div>
        </label>
      </div>
    );
  };

  // Render permission category section
  const renderPermissionCategory = (categoryName, categoryPermissions) => {
    return (
      <div key={categoryName} className={styles.permissionCategorySection}>
        <h3 className={styles.permissionCategoryTitle}>{categoryName}</h3>
        <div className={styles.permissionTogglesGrid}>
          {Object.keys(categoryPermissions).map(permission => 
            renderToggle(categoryName, permission, permission.replace(/_/g, ' '))
          )}
        </div>
      </div>
    );
  };

  return (
    <div className={styles.rolePermissionsMainContainer}>
      <div className={styles.permissionsPageHeader}>
        <h2>Role Permissions Management</h2>
        <p>Configure access permissions for different system components and features</p>
      </div>
      
      <div className={styles.permissionsCategoriesContainer}>
        {Object.keys(permissions).map(category => 
          renderPermissionCategory(category, permissions[category])
        )}
      </div>
      
      <div className={styles.permissionsActionButtons}>
        <button className={styles.savePermissionsButton} type="button">
          Save Permissions
        </button>
        <button className={styles.resetPermissionsButton} type="button">
          Reset to Default
        </button>
      </div>
    </div>
  );
};

export default RolePermissions;