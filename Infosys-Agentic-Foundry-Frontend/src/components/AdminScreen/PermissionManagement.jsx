import React, { useState, useEffect, useCallback, useRef } from "react";
import Cookies from "js-cookie";
import axios from "axios";
import styles from "./AgentAssignment.module.css";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios.js";
import { APIs, BASE_URL } from "../../constant";
import Loader from "../commonComponents/Loader";
import SVGIcons from "../../Icons/SVGIcons";

/**
 * PermissionManagement - Dynamic permission management component
 * Fetches permissions from API and builds UI dynamically based on response
 * No hardcoded permission structure - everything comes from API
 */
const PermissionManagement = ({ selectedRole, userDepartment }) => {
  const { addMessage } = useMessage();
  const { postData } = useFetch();
  const [permissions, setPermissions] = useState({});
  const [loading, setLoading] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);
  const fetchedRoleRef = useRef(null);

  /**
   * Build permissions structure dynamically from API response
   * Handles both nested access objects (read_access, add_access, etc.)
   * and standalone boolean permissions
   */
  const buildPermissionsFromResponse = useCallback((perms) => {
    if (!perms || typeof perms !== "object") {
      return {};
    }

    const dynamicPermissions = {};
    
    // Define known nested access categories
    const nestedAccessKeys = ["read_access", "add_access", "update_access", "delete_access", "execute_access"];
    const accessLabelMap = {
      read_access: "read",
      add_access: "create",
      update_access: "update",
      delete_access: "delete",
      execute_access: "execute_access",
    };
    
    // Process nested access objects (e.g., read_access: { tools: true, agents: false })
    nestedAccessKeys.forEach((accessType) => {
      if (perms[accessType] && typeof perms[accessType] === "object") {
        Object.entries(perms[accessType]).forEach(([entity, value]) => {
          // Capitalize entity name for display
          const categoryName = entity.charAt(0).toUpperCase() + entity.slice(1);
          if (!dynamicPermissions[categoryName]) {
            dynamicPermissions[categoryName] = {};
          }
          dynamicPermissions[categoryName][accessLabelMap[accessType]] = Boolean(value);
        });
      }
    });
    
    // Process standalone boolean permissions
    const standalonePermissions = Object.entries(perms).filter(
      ([key, value]) => !nestedAccessKeys.includes(key) && typeof value === "boolean"
    );
    
    // Dynamic category grouping - can be extended without code changes
    const categoryGroups = {
      // Chat-related permissions
      execution_steps_access: "Chat",
      tool_verifier_flag_access: "Chat",
      plan_verifier_flag_access: "Chat",
      online_evaluation_flag_access: "Chat",
      // Other Features
      vault_access: "Other Features",
      data_connector_access: "Other Features",
      evaluation_access: "Other Features",
      ground_truth_access: "Other Features",
    };
    
    standalonePermissions.forEach(([permKey, permValue]) => {
      // Use predefined category or auto-generate from permission name
      let categoryName = categoryGroups[permKey];
      if (!categoryName) {
        // Auto-generate: "some_new_access" -> "Some New"
        categoryName = permKey
          .replace(/_access$/, "")
          .replace(/_/g, " ")
          .replace(/\b\w/g, (l) => l.toUpperCase());
      }
      
      if (!dynamicPermissions[categoryName]) {
        dynamicPermissions[categoryName] = {};
      }
      dynamicPermissions[categoryName][permKey] = Boolean(permValue);
    });
    
    return dynamicPermissions;
  }, []);

  /**
   * Fetch permissions from API for selected role
   */
  const fetchPermissions = useCallback(async () => {
    const roleName = selectedRole?.name || selectedRole?.role_name;
    if (!roleName) {
      setPermissions({});
      fetchedRoleRef.current = null;
      return;
    }

    // Skip if already fetched for this role
    if (fetchedRoleRef.current === roleName) {
      return;
    }

    setLoading(true);
    setPermissions({});

    try {
      const url = `${BASE_URL}${APIs.GET_ROLE_PERMISSIONS}`;
      const response = await axios.post(
        url,
        {
          role_name: roleName,
          department_name: userDepartment || "",
        },
        {
          headers: {
            Authorization: `Bearer ${Cookies.get("jwt-token")}`,
          },
        }
      );

      const data = response.data;
      if (data?.success && data?.permissions) {
        const builtPermissions = buildPermissionsFromResponse(data.permissions);
        setPermissions(builtPermissions);
      }
      fetchedRoleRef.current = roleName;
    } catch (error) {
      if (error.response?.status !== 404) {
        console.error("Error fetching permissions:", error);
      }
      fetchedRoleRef.current = roleName;
    } finally {
      setLoading(false);
    }
  }, [selectedRole, userDepartment, buildPermissionsFromResponse]);

  // Fetch permissions when role changes
  useEffect(() => {
    const timer = setTimeout(fetchPermissions, 250);
    return () => clearTimeout(timer);
  }, [fetchPermissions]);

  /**
   * Handle toggle change for a permission
   */
  const handleToggleChange = (category, permission) => {
    setPermissions((prev) => {
      const categoryPerms = prev[category] || {};
      const hasRead = "read" in categoryPerms;
      
      // Enforce read-first rule: can't enable other permissions without read
      if (hasRead && permission !== "read" && !categoryPerms.read) {
        return prev;
      }
      
      // If disabling read, disable all permissions in category
      if (permission === "read" && categoryPerms.read) {
        const resetCategory = Object.keys(categoryPerms).reduce((acc, key) => {
          acc[key] = false;
          return acc;
        }, {});
        return { ...prev, [category]: resetCategory };
      }
      
      return {
        ...prev,
        [category]: {
          ...categoryPerms,
          [permission]: !categoryPerms[permission],
        },
      };
    });
  };

  /**
   * Save permissions to API
   */
  const handleSavePermissions = async () => {
    const roleName = selectedRole?.name || selectedRole?.role_name;
    if (!roleName) {
      addMessage("Please select a role first", "error");
      return;
    }

    setSaveLoading(true);
    try {
      // Build API payload from current permissions state
      const payload = {
        department_name: userDepartment || "",
        role_name: roleName,
      };

      // Rebuild nested access objects for API
      const accessMapping = {
        read: "read_access",
        create: "add_access",
        update: "update_access",
        delete: "delete_access",
        execute_access: "execute_access",
      };

      // Initialize access objects
      Object.values(accessMapping).forEach((key) => {
        payload[key] = {};
      });

      // Process each category
      Object.entries(permissions).forEach(([category, perms]) => {
        const entityKey = category.toLowerCase();
        
        Object.entries(perms).forEach(([permKey, permValue]) => {
          if (accessMapping[permKey]) {
            // This is a nested access permission (Tools/Agents)
            payload[accessMapping[permKey]][entityKey] = Boolean(permValue);
          } else {
            // This is a standalone boolean permission
            payload[permKey] = Boolean(permValue);
          }
        });
      });

      const response = await postData(APIs.SET_ROLE_PERMISSIONS, payload);
      if (response?.success) {
        addMessage("Permissions saved successfully!", "success");
        fetchedRoleRef.current = null; // Force refresh on next fetch
      } else {
        addMessage(response?.message || "Failed to save permissions", "error");
      }
    } catch (error) {
      console.error("Error saving permissions:", error);
      addMessage("Failed to save permissions. Please try again.", "error");
    } finally {
      setSaveLoading(false);
    }
  };

  /**
   * Reset permissions to original state
   */
  const handleResetPermissions = () => {
    fetchedRoleRef.current = null;
    fetchPermissions();
  };

  /**
   * Format permission label for display
   */
  const formatLabel = (permission) => {
    const labelMap = {
      read: "Read",
      create: "Create",
      update: "Update",
      delete: "Delete",
      execute_access: "Execute",
      execution_steps_access: "Execution Steps",
      tool_verifier_flag_access: "Tool Verifier",
      plan_verifier_flag_access: "Plan Verifier",
      online_evaluation_flag_access: "Online Evaluation",
      vault_access: "Vault",
      data_connector_access: "Data Connectors",
      evaluation_access: "Evaluation",
      ground_truth_access: "Ground Truth",
    };
    return labelMap[permission] || permission.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
  };

  /**
   * Get icon for category
   */
  const getCategoryIcon = (categoryName) => {
    const iconMap = {
      tools: "fa-screwdriver-wrench",
      agents: "fa-robot",
      chat: "nav-chat",
      "other features": "settings",
      vault: "vault-lock",
      "data connectors": "data-connectors",
      evaluation: "clipboard-check",
    };
    return iconMap[categoryName.toLowerCase()] || "settings";
  };

  /**
   * Render toggle switch
   */
  const renderToggle = (category, permission, label) => {
    const isChecked = permissions[category]?.[permission] || false;
    const hasRead = "read" in (permissions[category] || {});
    const isDisabled = hasRead && permission !== "read" && !permissions[category]?.read;

    return (
      <div
        key={permission}
        className={`${styles.toggleItem} ${isDisabled ? styles.toggleDisabled : ""} ${isChecked ? styles.toggleActive : ""}`}
      >
        <span className={styles.toggleLabel}>{label}</span>
        <label className={styles.toggleSwitch}>
          <input
            type="checkbox"
            checked={isChecked}
            onChange={() => handleToggleChange(category, permission)}
            disabled={isDisabled}
            className={styles.toggleInput}
          />
          <span className={styles.slider}></span>
        </label>
      </div>
    );
  };

  /**
   * Render permission category card
   */
  const renderCategory = (categoryName, categoryPermissions) => {
    const permKeys = Object.keys(categoryPermissions);
    // Ensure 'read' is first if it exists
    const orderedKeys = permKeys.includes("read")
      ? ["read", ...permKeys.filter((k) => k !== "read")]
      : permKeys;

    const hasActivePermission = Object.values(categoryPermissions).some((v) => v === true);

    return (
      <div
        key={categoryName}
        className={`${styles.permissionCard} ${hasActivePermission ? styles.permissionCardActive : ""}`}
      >
        <div className={styles.permissionCardHeader}>
          <div className={styles.permissionCardIcon}>
            <SVGIcons icon={getCategoryIcon(categoryName)} width={16} height={16} color="#ffffff" stroke="#ffffff" />
          </div>
          <h4 className={styles.permissionCardTitle}>{categoryName}</h4>
        </div>
        <div className={styles.permissionCardBody}>
          {orderedKeys.map((permission) => renderToggle(categoryName, permission, formatLabel(permission)))}
        </div>
      </div>
    );
  };

  // Show message if no role selected
  if (!selectedRole) {
    return (
      <div className={styles.permissionsSectionWrapper}>
        <div className={styles.noPermissions}>
          <p>Select a role to view and manage permissions</p>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.permissionsSectionWrapper}>
      {(loading || saveLoading) && <Loader />}
      
      {loading ? (
        <div className={styles.loadingState}>
          <p>Loading permissions...</p>
        </div>
      ) : Object.keys(permissions).length === 0 ? (
        <div className={styles.noPermissions}>
          <p>No permissions found for this role</p>
        </div>
      ) : (
        <div className={styles.permissionsGrid}>
          {Object.entries(permissions).map(([category, perms]) => renderCategory(category, perms))}
        </div>
      )}

      {!loading && Object.keys(permissions).length > 0 && (
        <div className={styles.permissionsFooterNoBorder}>
          <div className={styles.buttonClass}>
            <button
              type="button"
              className={styles.secondaryButton}
              onClick={handleResetPermissions}
              disabled={saveLoading || loading}
            >
              Cancel
            </button>
            <button
              type="button"
              className={styles.primaryButton}
              onClick={handleSavePermissions}
              disabled={saveLoading || loading}
            >
              {saveLoading ? "Saving..." : "Save Permissions"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default PermissionManagement;