import React, { useState, useEffect, useRef, useMemo } from "react";
import Cookies from "js-cookie";
import axios from "axios";

import styles from "./AgentAssignment.module.css";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios.js";
import { APIs, BASE_URL } from "../../constant";
import { extractErrorMessage } from "../../utils/errorUtils";
import Loader from "../commonComponents/Loader";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";
import TextField from "../../iafComponents/GlobalComponents/TextField/TextField";
import SVGIcons from "../../Icons/SVGIcons";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";

// HTTP status code constants
const HTTP_NOT_FOUND = 404;
const DEBOUNCE_DELAY_MS = 250;

// Role Permissions Component
const RolePermissionsSection = ({ selectedRole, userDepartment }) => {
  const { addMessage } = useMessage();
  const { postData } = useFetch();
  const [saveLoading, setSaveLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const fetchedRoleRef = useRef(null); // Track fetched role to prevent duplicate calls

  // State to manage all permissions - dynamically populated from API response
  const [permissions, setPermissions] = useState({});

  // Debounced fetchRolePermissions to prevent redundant API calls
  useEffect(() => {
    const handler = setTimeout(() => {
      fetchRolePermissions();
    }, DEBOUNCE_DELAY_MS);
    return () => clearTimeout(handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRole, userDepartment]);

  // Helper function to build permissions structure dynamically from API response
  const buildPermissionsFromResponse = (perms) => {
    const dynamicPermissions = {};

    // Define category mappings for nested access objects
    const accessCategories = ["read_access", "add_access", "update_access", "delete_access", "execute_access"];
    const accessLabelMap = {
      read_access: "read",
      add_access: "create",
      update_access: "update",
      delete_access: "delete",
      execute_access: "execute_access",
    };

    // Build Tools and Agents categories from nested access objects
    accessCategories.forEach((accessType) => {
      if (perms[accessType] && typeof perms[accessType] === "object") {
        Object.keys(perms[accessType]).forEach((entity) => {
          // Capitalize first letter for display (tools -> Tools, agents -> Agents)
          const categoryName = entity.charAt(0).toUpperCase() + entity.slice(1);
          if (!dynamicPermissions[categoryName]) {
            dynamicPermissions[categoryName] = {};
          }
          dynamicPermissions[categoryName][accessLabelMap[accessType]] = perms[accessType][entity] || false;
        });
      }
    });

    // Build other categories from standalone permission flags
    const standalonePermissions = Object.keys(perms).filter(
      (key) => !accessCategories.includes(key) && typeof perms[key] === "boolean"
    );

    // Group standalone permissions by category
    const categoryMapping = {
      execution_steps_access: "Chat",
      tool_verifier_flag_access: "Chat",
      plan_verifier_flag_access: "Chat",
      online_evaluation_flag_access: "Chat",
      validator_access: "Chat",
      file_context_access: "Chat",
      canvas_view_access: "Chat",
      context_access: "Chat",
      vault_access: "Other Features",
      data_connector_access: "Other Features",
      evaluation_access: "Other Features",
      knowledgebase_access: "Other Features",
    };

    standalonePermissions.forEach((permKey) => {
      // Use predefined category or create a new one based on permission name
      let categoryName = categoryMapping[permKey];
      if (!categoryName) {
        // Auto-generate category name from permission key (e.g., "some_new_access" -> "Some New")
        categoryName = permKey
          .replace(/_access$/, "")
          .replace(/_/g, " ")
          .replace(/\b\w/g, (l) => l.toUpperCase());
      }

      if (!dynamicPermissions[categoryName]) {
        dynamicPermissions[categoryName] = {};
      }
      dynamicPermissions[categoryName][permKey] = perms[permKey] || false;
    });

    // Ensure key permission categories always exist with expected permissions
    // These are core permissions that should always be visible in the UI
    const ensuredPermissions = {
      "Other Features": ["vault_access", "data_connector_access", "evaluation_access", "knowledgebase_access"],
      "Chat": ["execution_steps_access", "tool_verifier_flag_access", "plan_verifier_flag_access", "online_evaluation_flag_access", "validator_access", "file_context_access", "canvas_view_access", "context_access"],
    };

    Object.entries(ensuredPermissions).forEach(([category, permKeys]) => {
      if (!dynamicPermissions[category]) {
        dynamicPermissions[category] = {};
      }
      permKeys.forEach((permKey) => {
        // Only add if not already present from API
        if (!(permKey in dynamicPermissions[category])) {
          // Check if API returned this permission at root level
          dynamicPermissions[category][permKey] = perms[permKey] === true;
        }
      });
    });

    return dynamicPermissions;
  };

  // Move fetchRolePermissions outside useEffect
  async function fetchRolePermissions() {
    const roleName = selectedRole?.name || selectedRole?.role_name;
    if (!roleName) {
      // Reset permissions when no role is selected
      setPermissions({});
      fetchedRoleRef.current = null;
      return;
    }

    // Reset permissions to empty state before fetching
    setPermissions({});

    setLoading(true);

    try {
      // Use POST request with request body as per API spec
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

      // Handle API response format: dynamically build permissions from response
      if (data && data.success && data.permissions) {
        const perms = data.permissions;

        // Debug: Alert to confirm code is running
        console.warn("=== PERMISSIONS DEBUG START ===");
        console.warn("evaluation_access:", perms.evaluation_access, "type:", typeof perms.evaluation_access);

        // Dynamically build permissions structure from API response
        const dynamicPermissions = buildPermissionsFromResponse(perms);

        console.warn("Other Features:", JSON.stringify(dynamicPermissions["Other Features"]));
        console.warn("=== PERMISSIONS DEBUG END ===");

        setPermissions(dynamicPermissions);
      }
      // Mark as fetched
      fetchedRoleRef.current = roleName;
    } catch (error) {
      // Silently handle 404 errors - expected for roles without permissions
      if (error.response?.status !== HTTP_NOT_FOUND) {
        // Error handled silently
      }
      // Keep permissions as empty if fetch fails
      fetchedRoleRef.current = roleName; // Mark as fetched to prevent retries
    } finally {
      setLoading(false);
    }
  }


  // Handle toggle changes with RBAC logic
  const handleToggleChange = (category, permission) => {
    setPermissions((prev) => {
      // Only allow toggling non-read permissions if 'read' is checked
      const hasRead = Object.keys(prev[category] || {}).includes("read");
      if (hasRead && permission !== "read") {
        if (!prev[category]["read"]) {
          // Block any toggle if 'read' is not checked
          return prev;
        }
      }
      // If toggling 'read' off, uncheck all others in the category
      if (permission === "read") {
        const newReadValue = !prev[category][permission];
        if (!newReadValue) {
          // Uncheck all permissions in this category
          const resetCategory = Object.keys(prev[category]).reduce((acc, key) => {
            acc[key] = false;
            return acc;
          }, {});

          // Also reset dependent categories if they exist
          const updates = { ...prev, [category]: resetCategory };

          // Reset Chat permissions if Agents.read is being unchecked
          if (category === "Agents" && prev["Chat"]) {
            updates["Chat"] = Object.keys(prev["Chat"]).reduce((acc, key) => {
              acc[key] = false;
              return acc;
            }, {});
          }
          // Reset Vault permissions if Tools.read is being unchecked
          if (category === "Tools" && prev["Vault"]) {
            updates["Vault"] = Object.keys(prev["Vault"]).reduce((acc, key) => {
              acc[key] = false;
              return acc;
            }, {});
          }

          return updates;
        }
        // If toggling 'read' on, just toggle it
        return {
          ...prev,
          [category]: {
            ...prev[category],
            [permission]: newReadValue,
          },
        };
      } else {
        // For other permissions, allow toggle (read check passed above)
        const newValue = !prev[category][permission];
        const updates = {
          ...prev,
          [category]: {
            ...prev[category],
            [permission]: newValue,
          },
        };

        // --- CASCADING LOGIC: Agents create/update enables Tools read for admin/superadmin ---
        const userRole = Cookies.get("role");
        const isAdminOrSuper = userRole && ["admin", "superadmin"].includes(userRole.toLowerCase().replace(/\s|_/g, ""));
        if (
          isAdminOrSuper &&
          category === "Agents" &&
          (permission === "create" || permission === "update") &&
          newValue &&
          prev["Tools"] &&
          !prev["Tools"].read
        ) {
          updates["Tools"] = {
            ...prev["Tools"],
            read: true,
          };
        }

        // If unchecking Agents.execute_access, also reset Chat permissions
        if (category === "Agents" && permission === "execute_access" && !newValue && prev["Chat"]) {
          updates["Chat"] = Object.keys(prev["Chat"]).reduce((acc, key) => {
            acc[key] = false;
            return acc;
          }, {});
        }

        // If unchecking Tools.create or Tools.update, check if Vault should be reset
        if (category === "Tools" && (permission === "create" || permission === "update") && !newValue && prev["Vault"]) {
          const otherPerm = permission === "create" ? "update" : "create";
          const otherStillChecked = prev.Tools?.[otherPerm];
          if (!otherStillChecked) {
            updates["Vault"] = Object.keys(prev["Vault"]).reduce((acc, key) => {
              acc[key] = false;
              return acc;
            }, {});
          }
        }

        return updates;
      }
    });
  };

  // Handle save permissions - dynamically build API payload from current permissions
  const handleSavePermissions = async () => {
    try {
      setSaveLoading(true);

      // Transform the permissions state back to API format
      const permissionsData = {
        department_name: userDepartment || "",
        role_name: selectedRole.name || selectedRole.role_name,
      };

      // Build nested access objects from Tools and Agents categories
      const accessMapping = {
        read: "read_access",
        create: "add_access",
        update: "update_access",
        delete: "delete_access",
        execute_access: "execute_access",
      };

      // Initialize access objects
      Object.values(accessMapping).forEach((accessKey) => {
        permissionsData[accessKey] = {};
      });

      // Populate Tools and Agents permissions
      ["Tools", "Agents"].forEach((category) => {
        if (permissions[category]) {
          const entityKey = category.toLowerCase();
          Object.keys(permissions[category]).forEach((perm) => {
            const apiAccessKey = accessMapping[perm];
            if (apiAccessKey) {
              permissionsData[apiAccessKey][entityKey] = permissions[category][perm] || false;
            }
          });
        }
      });

      // Add standalone permissions from other categories
      Object.keys(permissions).forEach((category) => {
        if (category !== "Tools" && category !== "Agents") {
          Object.keys(permissions[category]).forEach((perm) => {
            // These are direct boolean flags in the API
            permissionsData[perm] = permissions[category][perm] || false;
          });
        }
      });

      const response = await postData(APIs.SET_ROLE_PERMISSIONS, permissionsData);

      if (response && response.success) {
        addMessage("Role permissions updated successfully!", "success");
        // Refresh permissions to ensure UI is in sync
        fetchedRoleRef.current = null;
      } else {
        const errorMsg = response?.message || response?.error || "Failed to update role permissions";
        addMessage(errorMsg, "error");
      }
    } catch (error) {
      console.error("Error saving permissions:", error);
      const errorMsg = extractErrorMessage(error).message || "Failed to update role permissions. Please try again.";
      addMessage(errorMsg, "error");
    } finally {
      setSaveLoading(false);
    }
  };

  // Handle reset permissions - dynamically reset all permissions to false
  const handleResetPermissions = () => {
    setPermissions((prev) => {
      const resetPermissions = {};
      Object.keys(prev).forEach((category) => {
        resetPermissions[category] = {};
        Object.keys(prev[category]).forEach((perm) => {
          resetPermissions[category][perm] = false;
        });
      });
      return resetPermissions;
    });
    // Permissions reset to defaults
    addMessage("Permissions reset to default", "success");
  };

  // Helper function to format permission labels - auto-generate from key if not in map
  const formatPermissionLabel = (permission) => {
    const labelMap = {
      read: "Read",
      create: "Create",
      update: "Update",
      delete: "Delete",
      execute_access: "Execute Access",
      execution_steps_access: "Execution Steps",
      tool_verifier_flag_access: "Tool Verifier Flag",
      plan_verifier_flag_access: "Plan Verifier Flag",
      online_evaluation_flag_access: "Online Evaluation Flag",
      vault_access: "Vault Access",
      data_connector_access: "Data Connectors Access",
      evaluation_access: "Evaluation Access",
    };
    return labelMap[permission] || permission.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
  };

  // Render toggle switch component with disabled state logic
  const renderToggle = (category, permission, label) => {
    const isChecked = permissions[category][permission];
    // Disable non-read checkboxes if read is not checked
    const hasRead = Object.keys(permissions[category] || {}).includes("read");
    const shouldDisable = hasRead && permission !== "read" && !permissions[category]["read"];
    return (
      <div
        key={permission}
        className={`${styles.toggleItem} ${shouldDisable ? styles.toggleDisabled : ""} ${isChecked ? styles.toggleActive : ""}`}
      >
        <span className={styles.toggleLabel}>{label}</span>
        <label className={styles.toggleSwitch}>
          <input
            type="checkbox"
            checked={isChecked}
            onChange={() => handleToggleChange(category, permission)}
            disabled={shouldDisable}
          />
          <span className={styles.toggleSlider}>
            <span className={styles.toggleKnob} />
          </span>
        </label>
      </div>
    );
  };

  // Render permission category section
  const renderPermissionCategory = (categoryName, categoryPermissions) => {
    // Ensure 'read' is always first if it exists in the category
    const permissionKeys = Object.keys(categoryPermissions);
    const hasRead = permissionKeys.includes("read");
    const orderedKeys = hasRead ? ["read", ...permissionKeys.filter((k) => k !== "read")] : permissionKeys;

    // Check if any permission in this category is active
    const hasActivePermission = Object.values(categoryPermissions).some((val) => val === true);

    // Get icon based on category - using SVGIcons from left nav (case-insensitive matching)
    const getCategoryIcon = (name) => {
      const lowerName = name.toLowerCase();
      const iconMap = {
        tools: "fa-screwdriver-wrench",
        agents: "fa-robot",
        vault: "vault-lock",
        "data connectors": "data-connectors",
        evaluation: "clipboard-check",
        chat: "nav-chat",
        "other features": "settings",
      };
      return iconMap[lowerName] || "settings";
    };

    return (
      <div key={categoryName} className={`${styles.permissionCard} ${hasActivePermission ? styles.permissionCardActive : ""}`}>
        <div className={styles.permissionCardHeader}>
          <div className={styles.permissionCardIcon}>
            <SVGIcons icon={getCategoryIcon(categoryName)} width={16} height={16} color="#ffffff" stroke="#ffffff" />
          </div>
          <h4 className={styles.permissionCardTitle}>{categoryName}</h4>
        </div>
        <div className={styles.permissionCardBody}>
          {orderedKeys.map((permission) => renderToggle(categoryName, permission, formatPermissionLabel(permission)))}
        </div>
      </div>
    );
  };

  // Remove the separate read-only view - handle everything in the main render
  // This ensures disabled fields are shown normally but just disabled

  return (
    <div className={styles.permissionsSectionWrapper}>
      {(saveLoading || loading) && <Loader />}
      {loading ? (
        <div className={styles.loadingState}>
          <p>Loading role permissions...</p>
        </div>
      ) : Object.keys(permissions).length === 0 ? (
        <div className={styles.noPermissions}>
          <p>Select a role to view and manage permissions</p>
        </div>
      ) : (
        <div className={styles.permissionsGrid}>
          {Object.keys(permissions).map((category) => {
            // Only show 'Chat' category if Agents.execute_access is selected
            if (category.toLowerCase() === "chat" && !permissions["Agents"]?.execute_access) {
              return null;
            }
            return renderPermissionCategory(category, permissions[category]);
          })}
        </div>
      )}
      {!loading && Object.keys(permissions).length > 0 && (
        <div className={styles.permissionsFooterNoBorder}>
          <div className={styles.buttonClass}>
            <IAFButton type="secondary" onClick={handleResetPermissions} disabled={saveLoading || loading}>
              Reset
            </IAFButton>
            <IAFButton type="primary" onClick={handleSavePermissions} disabled={saveLoading || loading} loading={saveLoading}>
              Save Permissions
            </IAFButton>
          </div>
        </div>
      )}
    </div>
  );
};

const RoleAgentAssignment = ({ externalSearchTerm = "", onPlusClickRef, onClearSearchRef }) => {
  const [roles, setRoles] = useState([]);
  const [loading, setLoading] = useState(false);
  const rolesLoadedRef = useRef(false); // Track if roles have been loaded

  // Internal search state (can be controlled externally)
  const [internalSearchTerm, setInternalSearchTerm] = useState("");
  const searchTerm = externalSearchTerm || internalSearchTerm;

  // Create role states
  const [newRoleName, setNewRoleName] = useState("");
  const [createRoleLoading, setCreateRoleLoading] = useState(false);
  const [showCreateRole, setShowCreateRole] = useState(false);

  const [selectedRole, setSelectedRole] = useState(null);

  // Delete confirmation states (matching Group tab pattern)
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);
  const [roleToDelete, setRoleToDelete] = useState(null);

  // User assignment states
  const [showAddUser, setShowAddUser] = useState(false);
  const [userSearchTerm, setUserSearchTerm] = useState("");
  const [assignUserLoading, setAssignUserLoading] = useState(false);

  const { addMessage } = useMessage();
  const { postData, deleteData, fetchData } = useFetch();

  // Get user's department and role from cookies
  const userDepartment = Cookies.get("department");
  const userRole = Cookies.get("role");

  // Check if user is Super Admin
  const isSuperAdmin = userRole?.toLowerCase().replace(/[\s_-]/g, "") === "superadmin";

  // Department selection state for SuperAdmin
  const [departmentsList, setDepartmentsList] = useState([]);
  const [selectedDepartment, setSelectedDepartment] = useState(userDepartment || "");
  const [departmentsLoading, setDepartmentsLoading] = useState(false);

  // Effective department for role fetching
  const effectiveDepartment = isSuperAdmin ? selectedDepartment : userDepartment;

  // Check if user is Super Admin (kept for future use with conditional rendering)
  // eslint-disable-next-line no-unused-vars
  const roleUpper = userRole ? userRole.toUpperCase().replace(/\s+/g, "") : "";

  // Filtered roles based on search term (both external and dropdown search)
  const filteredRoles = useMemo(() => {
    if (!searchTerm) return roles;
    return roles.filter((role) =>
      (role.name || role.role_name || "").toLowerCase().includes(searchTerm.toLowerCase())
    );
  }, [roles, searchTerm]);

  // Fetch departments list for SuperAdmin
  useEffect(() => {
    if (!isSuperAdmin) return;

    const fetchDepartments = async () => {
      setDepartmentsLoading(true);
      try {
        const response = await fetchData(APIs.GET_DEPARTMENTS_LIST);
        if (Array.isArray(response)) {
          // Extract department names from response
          const deptNames = response.map(dept =>
            typeof dept === "string" ? dept : (dept.department_name || dept.name || dept)
          );
          setDepartmentsList(deptNames);
        } else if (response?.departments && Array.isArray(response.departments)) {
          const deptNames = response.departments.map(dept =>
            typeof dept === "string" ? dept : (dept.department_name || dept.name || dept)
          );
          setDepartmentsList(deptNames);
        }
      } catch (err) {
        console.error("Failed to fetch departments:", err);
      } finally {
        setDepartmentsLoading(false);
      }
    };
    fetchDepartments();
  }, [isSuperAdmin, fetchData]);

  // Load roles from API based on effective department
  const loadRoles = async (forceReload = false) => {
    if (rolesLoadedRef.current && !forceReload) return;
    try {
      setLoading(true);
      let rolesArray = [];
      const token = Cookies.get("jwt-token");
      const headers = token ? { Authorization: `Bearer ${token}` } : {};

      if (effectiveDepartment) {
        try {
          const url = `${BASE_URL}${APIs.GET_DEPARTMENT_ROLES}${encodeURIComponent(effectiveDepartment)}/roles`;
          const response = await axios.get(url, { headers });
          const deptRolesResponse = response.data;
          if (Array.isArray(deptRolesResponse)) {
            rolesArray = deptRolesResponse;
          } else if (deptRolesResponse && Array.isArray(deptRolesResponse.roles)) {
            rolesArray = deptRolesResponse.roles;
          } else if (deptRolesResponse && Array.isArray(deptRolesResponse.data)) {
            rolesArray = deptRolesResponse.data;
          }
        } catch (deptError) {
          // Fallback to all roles if department roles fail
          const url = `${BASE_URL}${APIs.GET_ROLES}`;
          const response = await axios.get(url, { headers });
          const data = response.data;
          if (Array.isArray(data)) {
            rolesArray = data;
          } else if (data && Array.isArray(data.data)) {
            rolesArray = data.data;
          } else if (data && Array.isArray(data.roles)) {
            rolesArray = data.roles;
          } else if (data && data.result && Array.isArray(data.result)) {
            rolesArray = data.result;
          }
        }
      } else {
        const url = `${BASE_URL}${APIs.GET_ROLES}`;
        const response = await axios.get(url, { headers });
        const data = response.data;
        if (Array.isArray(data)) {
          rolesArray = data;
        } else if (data && Array.isArray(data.data)) {
          rolesArray = data.data;
        } else if (data && Array.isArray(data.roles)) {
          rolesArray = data.roles;
        } else if (data && data.result && Array.isArray(data.result)) {
          rolesArray = data.result;
        } else {
          rolesArray = [];
        }
      }

      // Normalize roles
      const normalizedRoles = rolesArray.map((r, idx) => {
        if (typeof r === "string") {
          return { id: `role-${idx}`, name: r, role_name: r };
        }
        return {
          id: r.id || r.role_id || `role-${idx}`,
          name: r.name || r.role_name || "",
          role_name: r.role_name || r.name || "",
        };
      });

      // Filter roles based on user type:
      // - Super Admin: Show all roles EXCEPT Super Admin
      // - Admin: Show all roles EXCEPT Admin and Super Admin
      const superAdminVariants = new Set(["super admin", "superadmin", "super-admin", "super_admin"]);
      const adminVariants = new Set(["admin"]);

      const filtered = normalizedRoles.filter((r) => {
        const n = (r.name || r.role_name || "").toLowerCase().trim();
        // Always exclude Super Admin for everyone
        if (superAdminVariants.has(n)) return false;
        // For Admin users, also exclude Admin role
        if (!isSuperAdmin && adminVariants.has(n)) return false;
        return true;
      });

      setRoles(filtered);
      rolesLoadedRef.current = true;

      // If nothing is selected yet, default to the first role in the filtered list
      if ((!selectedRole || Object.keys(selectedRole).length === 0) && filtered.length > 0) {
        setSelectedRole(filtered[0]);
      }
    } catch (error) {
      // Only show error message if it's not a 404 (endpoint doesn't exist)
      if (error?.response?.status !== HTTP_NOT_FOUND) {
        addMessage("Failed to load roles", "error");
      }
      setRoles([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (rolesLoadedRef.current) {
      return;
    }
    loadRoles();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Reload roles when SuperAdmin changes department selection
  useEffect(() => {
    if (isSuperAdmin && selectedDepartment) {
      rolesLoadedRef.current = false; // Reset to allow reload
      setSelectedRole(null); // Clear selected role when department changes
      loadRoles(true); // Force reload with new department
    }
  }, [selectedDepartment, isSuperAdmin]); // eslint-disable-line react-hooks/exhaustive-deps

  // Validate role name
  const MIN_ROLE_NAME_LENGTH = 2;
  const MAX_ROLE_NAME_LENGTH = 50;

  const validateRoleName = (name) => {
    if (!name.trim()) {
      return "Role name is required";
    }
    if (name.trim().length < MIN_ROLE_NAME_LENGTH) {
      return `Role name must be at least ${MIN_ROLE_NAME_LENGTH} characters`;
    }
    if (name.trim().length > MAX_ROLE_NAME_LENGTH) {
      return `Role name must be less than ${MAX_ROLE_NAME_LENGTH} characters`;
    }
    if (!/^[a-zA-Z0-9\s_-]+$/.test(name.trim())) {
      return "Role name can only contain letters, numbers, spaces, hyphens and underscores";
    }
    // Check if role already exists
    if (Array.isArray(roles)) {
      const existingRole = roles.find((role) => (role.name || role.role_name || "").toLowerCase() === name.trim().toLowerCase());
      if (existingRole) {
        return "A role with this name already exists";
      }
    }
    return "";
  };

  // Handle create role with department-specific endpoint
  const handleCreateRole = async () => {
    const validationError = validateRoleName(newRoleName);
    if (validationError) {
      addMessage(validationError, "error");
      return;
    }

    try {
      setCreateRoleLoading(true);
      const payload = { role_name: newRoleName.trim() };

      // Use department-specific endpoint for Admin users with department
      const apiUrl = effectiveDepartment
        ? `${APIs.ADD_DEPARTMENT_ROLE}${encodeURIComponent(effectiveDepartment)}/roles/add`
        : APIs.ADD_ROLE;

      const response = await postData(apiUrl, payload);

      // Normalize response for both endpoints
      const isSuccess = response && (response.success === true || response.status === "success");
      if (isSuccess) {
        addMessage("Role created successfully", "success");
        setNewRoleName("");
        setShowCreateRole(false); // Close modal on success
        rolesLoadedRef.current = false; // Reset to force reload
        await loadRoles(true); // Refresh the roles list
      } else {
        // Try to extract backend error message
        const errorMsg = response?.message || response?.error || response?.detail || "Failed to create role";
        addMessage(errorMsg, "error");
      }
    } catch (error) {
      console.error("Error creating role:", error);
      const errorMsg = extractErrorMessage(error).message || "Failed to create role";
      addMessage(errorMsg, "error");
    } finally {
      setCreateRoleLoading(false);
    }
  };

  // Confirm delete role (matching Group tab pattern)
  const handleConfirmDelete = async () => {
    if (!roleToDelete?.name && !roleToDelete?.role_name) {
      setShowDeleteConfirmation(false);
      setRoleToDelete(null);
      return;
    }

    const roleName = roleToDelete.name || roleToDelete.role_name;

    // Double-check: Prevent deletion of system roles
    const roleNameLower = roleName.toLowerCase();
    if (roleNameLower.toLowerCase() === "admin" || roleNameLower.toLowerCase() === "superadmin" || roleNameLower.toLowerCase() === "super admin") {
      addMessage("System roles (Admin and SuperAdmin) cannot be deleted for security reasons.", "error");
      setShowDeleteConfirmation(false);
      setRoleToDelete(null);
      return;
    }

    setLoading(true);
    try {
      // Use DELETE request to /departments/{department_name}/roles/{role_name} endpoint
      const deleteUrl = `${APIs.DELETE_ROLE}/${encodeURIComponent(effectiveDepartment)}/roles/${encodeURIComponent(roleName)}`;
      const result = await deleteData(deleteUrl);

      if (result && result.success !== false) {
        addMessage(`Role "${roleName}" deleted successfully!`, "success");

        // Reset role selection if deleted role was selected
        if (selectedRole && (selectedRole.name === roleName || selectedRole.role_name === roleName)) {
          setSelectedRole(null);
        }

        // Reload roles with force reload
        rolesLoadedRef.current = false; // Reset to force reload
        await loadRoles(true);
      } else {
        throw new Error(result?.message || "Failed to delete role");
      }
    } catch (error) {
      console.error("Error deleting role:", error);
      const errorMsg = extractErrorMessage(error).message || "Failed to delete role. Please try again.";
      addMessage(errorMsg, "error");
    } finally {
      setLoading(false);
      setShowDeleteConfirmation(false);
      setRoleToDelete(null);
    }
  };

  const handleAssignUser = async () => {
    if (!selectedRole || !userSearchTerm.trim()) {
      addMessage("Please enter a user email", "error");
      return;
    }

    // Validate email format
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(userSearchTerm.trim())) {
      addMessage("Please enter a valid email address", "error");
      return;
    }

    try {
      setAssignUserLoading(true);
      const payload = {
        role_id: selectedRole.id || selectedRole.role_id,
        user_email: userSearchTerm.trim(),
        role_name: selectedRole.name || selectedRole.role_name,
      };

      await postData(APIs.ASSIGN_USER_ROLE, payload);
      addMessage(`User "${payload.user_email}" assigned to role "${payload.role_name}" successfully`, "success");

      setShowAddUser(false);
      setSelectedRole(null);
      setUserSearchTerm("");
    } catch (error) {
      console.error("Error assigning user to role:", error);
      addMessage("Failed to assign user to role", "error");
    } finally {
      setAssignUserLoading(false);
    }
  };

  // Handler to open create role modal (exposed to parent via ref)
  const handlePlusIconClick = React.useCallback(() => {
    setShowCreateRole(true);
    setNewRoleName("");
  }, []);

  // Clear search handler (exposed to parent via ref)
  const clearSearch = React.useCallback(() => {
    setInternalSearchTerm("");
  }, []);

  // Expose handlePlusIconClick to parent via ref
  useEffect(() => {
    if (onPlusClickRef) {
      onPlusClickRef.current = handlePlusIconClick;
    }
  }, [onPlusClickRef, handlePlusIconClick]);

  // Expose clearSearch to parent via ref
  useEffect(() => {
    if (onClearSearchRef) {
      onClearSearchRef.current = clearSearch;
    }
  }, [onClearSearchRef, clearSearch]);

  // Handle delete click from dropdown list
  const handleDeleteFromList = (role, event) => {
    event.stopPropagation();

    // Check if trying to delete system-critical roles
    const roleName = (role.name || role.role_name || "").toLowerCase();
    const isSystemRole = roleName === "admin" || roleName === "superadmin" || roleName === "super admin";

    if (isSystemRole) {
      addMessage("System roles (Admin and SuperAdmin) cannot be deleted for security reasons.", "error");
      return;
    }

    // Set the role to delete and show confirmation
    setRoleToDelete(role);
    setShowDeleteConfirmation(true);
  };

  if (loading && roles.length === 0) {
    return (
      <div className={styles.agentAssignmentContainer}>
        <Loader />
      </div>
    );
  }

  // Get selected role name for dropdown
  const selectedRoleName = selectedRole ? selectedRole.name || selectedRole.role_name : "";

  return (
    <div className={styles.agentAssignmentContainer}>
      {loading && <Loader />}

      {/* Header Row: Department Dropdown (SuperAdmin) + Role Dropdown */}
      <div className={styles.roleHeaderRow}>
        {/* Department Dropdown for SuperAdmin */}
        {isSuperAdmin && (
          <div className={styles.roleDropdownWithActions}>
            <div className={styles.customRoleDropdown}>
              <label className={styles.controlLabel}>
                Select Department
              </label>
              <NewCommonDropdown
                options={departmentsList}
                selected={selectedDepartment}
                onSelect={(value) => setSelectedDepartment(value)}
                placeholder={departmentsLoading ? "Loading departments..." : "Select a department"}
                disabled={departmentsLoading}
                showSearch={true}
              />
            </div>
          </div>
        )}

        {/* Role Dropdown using NewCommonDropdown */}
        <div className={styles.roleDropdownWithActions}>
          <div className={styles.customRoleDropdown}>
            <label className={styles.controlLabel}>
              Select Role
            </label>
            <NewCommonDropdown
              options={roles.map((r) => r.name || r.role_name)}
              selected={selectedRoleName}
              onSelect={(value) => {
                const role = roles.find((r) => (r.name || r.role_name) === value);
                if (role) setSelectedRole(role);
              }}
              placeholder="Select Role"
              showSearch={true}
              onOptionDelete={(optName) => {
                const role = roles.find((r) => (r.name || r.role_name) === optName);
                if (role) {
                  handleDeleteFromList(role, { stopPropagation: () => { } });
                }
              }}
            />
          </div>
        </div>
      </div>

      {/* Role Permissions Section - Show when a role is selected */}
      {selectedRole && <RolePermissionsSection selectedRole={selectedRole} userDepartment={effectiveDepartment} />}

      {/* Create Role Modal - Using FullModal for consistency */}
      {showCreateRole && (
        <FullModal
          isOpen={showCreateRole}
          onClose={() => {
            setShowCreateRole(false);
            setNewRoleName("");
          }}
          title="Create New Role"
          footer={
            <div className={styles.modalFooterButtons}>
              <IAFButton
                type="secondary"
                onClick={() => {
                  setShowCreateRole(false);
                  setNewRoleName("");
                }}
              >
                Cancel
              </IAFButton>
              <IAFButton
                type="primary"
                onClick={handleCreateRole}
                disabled={createRoleLoading || !newRoleName.trim()}
                loading={createRoleLoading}
              >
                Create Role
              </IAFButton>
            </div>
          }
        >
          <div className={styles.modernFormContainer}>
            <div className={styles.formFieldGroup}>
              <TextField
                label="Role Name"
                value={newRoleName}
                onChange={(e) => setNewRoleName(e.target.value)}
                placeholder="Enter role name (e.g., Manager, Developer)"
                maxLength={50}
                required
              />
              <p className={styles.fieldHint}>
                Role names should be descriptive and indicate the user's function in the system.
              </p>
            </div>
          </div>
        </FullModal>
      )}

      {/* Add User to Role Modal - Using FullModal for consistency */}
      {showAddUser && (
        <FullModal
          isOpen={showAddUser}
          onClose={() => {
            setShowAddUser(false);
            setSelectedRole(null);
            setUserSearchTerm("");
          }}
          title={`Add User to Role: ${selectedRole?.name || selectedRole?.role_name}`}
          footer={
            <div className={styles.modalFooterButtons}>
              <IAFButton
                type="secondary"
                onClick={() => {
                  setShowAddUser(false);
                  setSelectedRole(null);
                  setUserSearchTerm("");
                }}
              >
                Cancel
              </IAFButton>
              <IAFButton
                type="primary"
                onClick={handleAssignUser}
                disabled={assignUserLoading || !userSearchTerm.trim()}
                loading={assignUserLoading}
              >
                Add User
              </IAFButton>
            </div>
          }
        >
          <div className={styles.modernFormContainer}>
            <div className={styles.formFieldGroup}>
              <TextField
                label="User Email"
                type="email"
                value={userSearchTerm}
                onChange={(e) => setUserSearchTerm(e.target.value)}
                placeholder="Enter user email address"
                required
              />
              <p className={styles.fieldHint}>
                Enter the email address of the user you want to assign to this role.
              </p>
            </div>
          </div>
        </FullModal>
      )}

      {/* Delete Role Confirmation Modal */}
      {showDeleteConfirmation && (
        <ConfirmationModal
          message={`Are you sure you want to delete the role "${roleToDelete?.name || roleToDelete?.role_name
            }"? This action cannot be undone and will remove all permissions associated with this role.`}
          onConfirm={handleConfirmDelete}
          setShowConfirmation={setShowDeleteConfirmation}
        />
      )}
    </div>
  );
};

export default RoleAgentAssignment;
