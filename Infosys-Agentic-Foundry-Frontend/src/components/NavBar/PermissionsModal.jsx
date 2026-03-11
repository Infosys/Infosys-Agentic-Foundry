import React from "react";
import styles from "./PermissionsModal.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { usePermissions } from "../../context/PermissionsContext";
import Cookies from "js-cookie";
import FullModal from "../../iafComponents/GlobalComponents/FullModal/FullModal";

/**
 * PermissionsModal - Displays current user's role-based permissions
 * 
 * This modal shows a read-only view of the permissions assigned to the
 * current user's role using the standard FullModal component.
 * 
 * @param {boolean} isOpen - Controls modal visibility
 * @param {function} onClose - Callback to close the modal
 */
const PermissionsModal = ({ isOpen, onClose }) => {
  const { permissions, loading } = usePermissions();
  const role = Cookies.get("role") || "Guest";
  const department = Cookies.get("department") || "";

  // Render a permission status indicator
  const renderPermissionBadge = (value) => {
    return (
      <span className={`${styles.permissionBadge} ${value ? styles.enabled : styles.disabled}`}>
        <SVGIcons
          icon={value ? "circle-check" : "circle-x"}
          width={14}
          height={14}
          color={value ? "var(--success-color)" : "#e74c3c"}
        />
        <span>{value ? "Enabled" : "Disabled"}</span>
      </span>
    );
  };

  // Organize permissions into categories for better display
  const permissionCategories = {
    Tools: {
      icon: "fa-screwdriver-wrench",
      items: [
        { key: "read_access.tools", label: "Read Access" },
        { key: "add_access.tools", label: "Create Access" },
        { key: "update_access.tools", label: "Update Access" },
        { key: "delete_access.tools", label: "Delete Access" },
        { key: "execute_access.tools", label: "Execute Access" },
      ],
    },
    Agents: {
      icon: "fa-robot",
      items: [
        { key: "read_access.agents", label: "Read Access" },
        { key: "add_access.agents", label: "Create Access" },
        { key: "update_access.agents", label: "Update Access" },
        { key: "delete_access.agents", label: "Delete Access" },
        { key: "execute_access.agents", label: "Execute Access" },
      ],
    },
    Chat: {
      icon: "nav-chat",
      items: [
        { key: "execution_steps_access", label: "Execution Steps" },
        { key: "tool_verifier_flag_access", label: "Tool Verifier Flag" },
        { key: "plan_verifier_flag_access", label: "Plan Verifier Flag" },
        { key: "online_evaluation_flag_access", label: "Online Evaluation Flag" },
        { key: "validator_access", label: "Validator" },
        { key: "file_context_access", label: "File Context" },
        { key: "canvas_view_access", label: "Canvas View" },
        { key: "context_access", label: "Context" },
      ],
    },
    "Other Features": {
      icon: "settings",
      items: [
        { key: "vault_access", label: "Vault Access" },
        { key: "data_connector_access", label: "Data Connectors Access" },
        { key: "evaluation_access", label: "Evaluation Access" },
        { key: "knowledgebase_access", label: "Knowledge Base Access" },
      ],
    },
  };

  // Get permission value from nested permissions object
  const getPermissionValue = (keyPath) => {
    const parts = keyPath.split(".");
    let current = permissions;

    for (const p of parts) {
      if (current && Object.prototype.hasOwnProperty.call(current, p)) {
        current = current[p];
      } else {
        return false;
      }
    }

    return typeof current === "boolean" ? current : false;
  };

  // Header info for FullModal
  const headerInfo = [
    { label: "Role", value: role },
    ...(department ? [{ label: "Department", value: department }] : []),
  ];

  return (
    <FullModal
      isOpen={isOpen}
      onClose={onClose}
      title="Role Permissions"
      headerInfo={headerInfo}
      loading={loading}
      closeOnOverlayClick={true}
      closeOnEscape={true}
    >
      <div className={styles.content}>
        <div className={styles.infoNote}>
          <SVGIcons icon="info" width={16} height={16} fill="var(--app-primary-color)" />
          <span>Below are the permissions assigned to your role. Contact your administrator for any changes.</span>
        </div>

        <div className={styles.categoriesGrid}>
          {Object.entries(permissionCategories).map(([categoryName, category]) => (
            <div key={categoryName} className={styles.categoryCard}>
              <div className={styles.categoryHeader}>
                <SVGIcons icon={category.icon} width={18} height={18} fill="var(--app-primary-color)" />
                <h3 className={styles.categoryTitle}>{categoryName}</h3>
              </div>
              <div className={styles.permissionsList}>
                {category.items.map((item) => (
                  <div key={item.key} className={styles.permissionRow}>
                    <span className={styles.permissionLabel}>{item.label}</span>
                    {renderPermissionBadge(getPermissionValue(item.key))}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </FullModal>
  );
};

export default PermissionsModal;
