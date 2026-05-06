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
    Agents: {
      create: false,
      update: false,
      read: false,
      delete: false,
      execute_access: false,
      export_agents_access: false
    },
    "MCP Servers": {
      read: false,
      create: false,
      update: false,
      delete: false,
      execute_access: false
    },
    Workflows: {
      read: false,
      create: false,
      update: false,
      delete: false,
      execute_access: false
    },
    Chat: {
      execution_steps_access: false,
      tool_verifier_flag_access: false,
      plan_verifier_flag_access: false,
      evaluation: false
    },
    Vault: {
      vault_access: false
    },
    "Data Connectors": {
      data_connector_access: false
    },
    "Other Features": {
      knowledgebase_access: false,
      evaluation_access: false
    }
  });

  // Handle toggle changes
  const handleToggleChange = (category, permission) => {
    setPermissions(prev => {
      const newValue = !prev[category][permission];
      const updatedCategory = {
        ...prev[category],
        [permission]: newValue
      };

      // When delete is enabled, also enable update
      if (permission === "delete" && newValue && "update" in updatedCategory) {
        updatedCategory.update = true;
      }

      // When update is disabled, also disable delete
      if (permission === "update" && !newValue && "delete" in updatedCategory) {
        updatedCategory.delete = false;
      }

      return {
        ...prev,
        [category]: updatedCategory
      };
    });
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