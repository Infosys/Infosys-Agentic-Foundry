import React, { useState, useEffect, useRef } from "react";

import styles from "./AgentAssignment.module.css";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios.js";
import { APIs } from "../../constant";
import Loader from "../commonComponents/Loader";
import Modal from "./commonComponents/Modal";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";

// Role Permissions Component
const RolePermissionsSection = ({ selectedRole }) => {
  const { addMessage } = useMessage();
  const { fetchData, postData } = useFetch();
  const [saveLoading, setSaveLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const permissionsFetchedForRole = useRef(null); // Track which role permissions were fetched

  // State to manage all permissions organized by categories
  const [permissions, setPermissions] = useState({
    Tools: {
      read: false,
      create: false,
      update: false,
      delete: false,
      execute_access: false,
    },
    agents: {
      create: false,
      update: false,
      read: false,
      delete: false,
      execute_access: false,
    },
    chat: {
      execution_steps_access: false,
      tool_verifier_flag_access: false,
      plan_verifier_flag_access: false,
      evaluation: false,
    },
    vault: {
      vault_access: false,
    },
    "Data Connectors": {
      data_connector_access: false,
    },
  });

  // Fetch existing permissions for the selected role
  useEffect(() => {
    const fetchRolePermissions = async () => {
      if (!selectedRole || (!selectedRole.name && !selectedRole.role_name)) return;

      const roleName = selectedRole.name || selectedRole.role_name;

      // Skip if we already fetched permissions for this role
      if (permissionsFetchedForRole.current === roleName) {
        return;
      }
      permissionsFetchedForRole.current = roleName;

      // Clear any previous messages to prevent popup conflicts
      setLoading(true);

      try {
        const response = await fetchData(`${APIs.GET_ROLE_PERMISSIONS}/${encodeURIComponent(roleName)}`);

        if (response && response.success && response.permissions) {
          const perms = response.permissions;
          // Transform API response to our permissions structure
          setPermissions({
            Tools: {
              read: perms.read_access?.tools || false,
              create: perms.add_access?.tools || false,
              update: perms.update_access?.tools || false,
              delete: perms.delete_access?.tools || false,
              execute_access: perms.execute_access?.tools || false,
            },
            agents: {
              create: perms.add_access?.agents || false,
              update: perms.update_access?.agents || false,
              read: perms.read_access?.agents || false,
              delete: perms.delete_access?.agents || false,
              execute_access: perms.execute_access?.agents || false,
            },
            chat: {
              execution_steps_access: perms.execution_steps_access || false,
              tool_verifier_flag_access: perms.tool_verifier_flag_access || false,
              plan_verifier_flag_access: perms.plan_verifier_flag_access || false,
              evaluation: perms.evaluation_flag_access || false,
            },
            vault: {
              vault_access: perms.vault_access || false,
            },
            "Data Connectors": {
              data_connector_access: perms.data_connector_access || false,
            },
          });

          // Permissions loaded successfully
        } else {
          // If no response or API returns success: false, silently use defaults
          // This is expected behavior for roles that don't have permissions set yet
          // No need to show error popup as this is normal
        }
      } catch (error) {
        // Only log in development to avoid console spam
        if (process.env.NODE_ENV === "development") {
          console.error("Error fetching role permissions:", error);
        }
        // Silently handle the error - don't show popup for expected API failures
        // This prevents annoying error popups when endpoints don't exist yet
      } finally {
        setLoading(false);
      }
    };

    fetchRolePermissions();
  }, [selectedRole]); // eslint-disable-line react-hooks/exhaustive-deps

  // Cleanup effect when role changes to prevent message conflicts
  useEffect(() => {
    return () => {
      // Reset any loading states when component unmounts or role changes
      setLoading(false);
      setSaveLoading(false);
    };
  }, [selectedRole]);

  // Reset the fetch tracker when role changes so new role can be fetched
  useEffect(() => {
    const currentRoleName = selectedRole?.name || selectedRole?.role_name;
    if (currentRoleName && permissionsFetchedForRole.current !== currentRoleName) {
      permissionsFetchedForRole.current = null; // Allow fetch for new role
    }
  }, [selectedRole]);

  // Handle toggle changes
  const handleToggleChange = (category, permission) => {
    setPermissions((prev) => ({
      ...prev,
      [category]: {
        ...prev[category],
        [permission]: !prev[category][permission],
      },
    }));

    // Permissions updated
  };

  // Handle save permissions
  const handleSavePermissions = async () => {
    try {
      setSaveLoading(true);

      // Transform the permissions state to match the API format
      const permissionsData = {
        role_name: selectedRole.name || selectedRole.role_name,
        read_access: {
          tools: permissions.Tools.read,
          agents: permissions.agents.read,
        },
        add_access: {
          tools: permissions.Tools.create,
          agents: permissions.agents.create,
        },
        update_access: {
          tools: permissions.Tools.update,
          agents: permissions.agents.update,
        },
        delete_access: {
          tools: permissions.Tools.delete,
          agents: permissions.agents.delete,
        },
        execute_access: {
          tools: permissions.Tools.execute_access,
          agents: permissions.agents.execute_access,
        },
        execution_steps_access: permissions.chat.execution_steps_access,
        tool_verifier_flag_access: permissions.chat.tool_verifier_flag_access,
        plan_verifier_flag_access: permissions.chat.plan_verifier_flag_access,
        evaluation_flag_access: permissions.chat.evaluation,
        vault_access: permissions.vault.vault_access,
        data_connector_access: permissions["Data Connectors"].data_connector_access,
      };

      const response = await postData(APIs.SET_ROLE_PERMISSIONS, permissionsData);

      if (response && response.success) {
        addMessage("Role permissions updated successfully!", "success");
        // Permissions saved successfully
      } else {
        addMessage("Failed to update role permissions", "error");
      }
    } catch (error) {
      console.error("Error saving permissions:", error);
      addMessage("Failed to update role permissions. Please try again.", "error");
    } finally {
      setSaveLoading(false);
    }
  };

  // Handle reset permissions
  const handleResetPermissions = () => {
    setPermissions({
      Tools: {
        read: false,
        create: false,
        update: false,
        delete: false,
        execute_access: false,
      },
      agents: {
        create: false,
        update: false,
        read: false,
        delete: false,
        execute_access: false,
      },
      chat: {
        execution_steps_access: false,
        tool_verifier_flag_access: false,
        plan_verifier_flag_access: false,
        evaluation: false,
      },
      vault: {
        vault_access: false,
      },
      "Data Connectors": {
        data_connector_access: false,
      },
    });
    // Permissions reset to defaults
    addMessage("Permissions reset to default", "success");
  };

  // Render toggle switch component
  const renderToggle = (category, permission, label) => {
    const isChecked = permissions[category][permission];
    return (
      <div key={permission} className={styles.checkboxLabel}>
        <input type="checkbox" checked={isChecked} onChange={() => handleToggleChange(category, permission)} />
        <span>{label}</span>
      </div>
    );
  };

  // Render permission category section
  const renderPermissionCategory = (categoryName, categoryPermissions) => {
    return (
      <div key={categoryName} className={styles.formSection}>
        <h4>{categoryName}</h4>
        <div className={styles.checkboxGroup}>{Object.keys(categoryPermissions).map((permission) => renderToggle(categoryName, permission, permission.replace(/_/g, " ")))}</div>
      </div>
    );
  };

  // Remove the separate read-only view - handle everything in the main render
  // This ensures disabled fields are shown normally but just disabled

  return (
    <div className={styles.assignmentsSection}>
      {(saveLoading || loading) && <Loader />}
      <h3>Permissions for Role: {selectedRole.name || selectedRole.role_name}</h3>
      <div style={{ padding: "20px" }}>
        {loading ? (
          <div style={{ textAlign: "center", padding: "40px" }}>
            <p>Loading role permissions...</p>
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
              gap: "20px",
              marginBottom: "25px",
            }}>
            {Object.keys(permissions).map((category) => renderPermissionCategory(category, permissions[category]))}
          </div>
        )}
        {!loading && (
          <div className={styles.modalFooter}>
            <div className={styles.buttonClass}>
              <button className="iafButton iafButtonPrimary" type="button" onClick={handleSavePermissions} disabled={saveLoading || loading}>
                {saveLoading ? "Saving..." : "Save Permissions"}
              </button>
              <button className="iafButton iafButtonSecondary" type="button" onClick={handleResetPermissions} disabled={saveLoading || loading}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

const RoleAgentAssignment = () => {
  const [roles, setRoles] = useState([]);
  const [loading, setLoading] = useState(false);
  const initialFetchDone = useRef(false);

  // Create role states
  const [newRoleName, setNewRoleName] = useState("");
  const [createRoleLoading, setCreateRoleLoading] = useState(false);
  const [showCreateRole, setShowCreateRole] = useState(false);

  const [selectedRole, setSelectedRole] = useState(null);

  // Role dropdown states
  const [showRoleDropdown, setShowRoleDropdown] = useState(false);
  const [roleSearchTerm, setRoleSearchTerm] = useState("");
  const [highlightedRoleIndex, setHighlightedRoleIndex] = useState(-1);

  // Delete confirmation states (matching Group tab pattern)
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);
  const [roleToDelete, setRoleToDelete] = useState(null);

  // User assignment states
  const [showAddUser, setShowAddUser] = useState(false);
  const [userSearchTerm, setUserSearchTerm] = useState("");
  const [assignUserLoading, setAssignUserLoading] = useState(false);

  const { addMessage } = useMessage();
  const { fetchData, postData, deleteData } = useFetch();

  // Load roles from API
  const loadRoles = async () => {
    try {
      setLoading(true);
      const response = await fetchData(APIs.GET_ROLES);

      // Handle different response structures
      let rolesArray = [];
      if (Array.isArray(response)) {
        rolesArray = response;
      } else if (response && Array.isArray(response.data)) {
        rolesArray = response.data;
      } else if (response && Array.isArray(response.roles)) {
        rolesArray = response.roles;
      } else if (response && response.result && Array.isArray(response.result)) {
        rolesArray = response.result;
      } else {
        console.warn("Unexpected roles response structure:", response);
        rolesArray = [];
      }

      // Filter out internal roles like admin and super admin (case-insensitive)
      const deny = new Set(["admin", "super admin", "superadmin", "super-admin", "super_admin"]);
      const filtered = rolesArray.filter((r) => {
        const n = (r.name || r.role_name || "").toLowerCase().trim();
        return !deny.has(n);
      });

      setRoles(filtered);
      // If nothing is selected yet, default to the first role in the filtered list
      if ((!selectedRole || Object.keys(selectedRole).length === 0) && filtered.length > 0) {
        setSelectedRole(filtered[0]);
      }
    } catch (error) {
      // Only log in development to avoid console spam
      if (process.env.NODE_ENV === "development") {
        console.error("Error loading roles:", error);
      }
      // Only show error message if it's not a 404 (endpoint doesn't exist)
      if (error?.response?.status !== 404) {
        addMessage("Failed to load roles", "error");
      }
      setRoles([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (initialFetchDone.current) {
      return;
    }
    initialFetchDone.current = true;
    loadRoles();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Filter roles based on search term
  const filteredRoles = Array.isArray(roles) ? roles.filter((role) => (role.name || role.role_name || "").toLowerCase().includes(roleSearchTerm.toLowerCase())) : [];

  // Role dropdown handlers
  const handleRoleSelection = (role) => {
    setSelectedRole(role);
    setRoleSearchTerm("");
    setShowRoleDropdown(false);
    setHighlightedRoleIndex(-1);
  };

  const handleRoleDropdownToggle = () => {
    const newShowState = !showRoleDropdown;
    setShowRoleDropdown(newShowState);

    if (newShowState && selectedRole) {
      // Find the selected role in the filtered list and highlight it
      const selectedIndex = filteredRoles.findIndex((role) => (role.id || role.role_id) === (selectedRole.id || selectedRole.role_id));
      if (selectedIndex !== -1) {
        setHighlightedRoleIndex(selectedIndex);
      }
    } else if (!newShowState) {
      setHighlightedRoleIndex(-1);
    }
  };

  const handleRoleKeyDown = (event) => {
    if (!showRoleDropdown) {
      if (event.key === "Enter" || event.key === " " || event.key === "ArrowDown") {
        event.preventDefault();
        setShowRoleDropdown(true);
        setHighlightedRoleIndex(0);
      }
      return;
    }

    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        setHighlightedRoleIndex((prev) => (prev < filteredRoles.length - 1 ? prev + 1 : prev));
        break;
      case "ArrowUp":
        event.preventDefault();
        setHighlightedRoleIndex((prev) => (prev > 0 ? prev - 1 : prev));
        break;
      case "Enter":
        event.preventDefault();
        if (highlightedRoleIndex >= 0 && filteredRoles[highlightedRoleIndex]) {
          handleRoleSelection(filteredRoles[highlightedRoleIndex]);
        }
        break;
      case "Escape":
        event.preventDefault();
        setShowRoleDropdown(false);
        setHighlightedRoleIndex(-1);
        break;
      default:
        break;
    }
  };

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (!event.target.closest(`.${styles.searchableDropdownSmall}`)) {
        setShowRoleDropdown(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

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

  // Handle create role
  const handleCreateRole = async () => {
    const validationError = validateRoleName(newRoleName);
    if (validationError) {
      addMessage(validationError, "error");
      return;
    }

    try {
      setCreateRoleLoading(true);
      const payload = { role_name: newRoleName.trim() };
      const response = await postData(APIs.ADD_ROLE, payload);

      if (response) {
        addMessage("Role created successfully", "success");
        setNewRoleName("");
        setShowCreateRole(false); // Close modal on success
        await loadRoles(); // Refresh the roles list
      }
    } catch (error) {
      console.error("Error creating role:", error);
      addMessage("Failed to create role", "error");
    } finally {
      setCreateRoleLoading(false);
    }
  };

  // Handle delete role click (matching Group tab pattern)
  const handleDeleteClick = (role, event) => {
    // Prevent dropdown from closing
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
    setShowRoleDropdown(false);
  };

  // Confirm delete role from modal
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
    if (roleNameLower === "admin" || roleNameLower === "superadmin" || roleNameLower === "super admin") {
      addMessage("System roles (Admin and SuperAdmin) cannot be deleted for security reasons.", "error");
      setShowDeleteConfirmation(false);
      setRoleToDelete(null);
      return;
    }

    setLoading(true);
    try {
      // Use DELETE request to /roles/{role_name} endpoint
      const deleteUrl = `${APIs.DELETE_ROLE}/${encodeURIComponent(roleName)}`;
      const result = await deleteData(deleteUrl);

      if (result && result.success !== false) {
        addMessage(`Role "${roleName}" deleted successfully!`, "success");

        // Reset role selection if deleted role was selected
        if (selectedRole && (selectedRole.name === roleName || selectedRole.role_name === roleName)) {
          setSelectedRole(null);
        }

        // Reload roles
        await loadRoles();
      } else {
        throw new Error(result?.message || "Failed to delete role");
      }
    } catch (error) {
      console.error("Error deleting role:", error);
      if (error.message && error.message.includes("401")) {
        addMessage("Authentication failed. Please log in again.", "error");
      } else if (error.message && error.message.includes("403")) {
        addMessage("Only administrators can delete roles. Please contact your administrator.", "error");
      } else {
        addMessage("Failed to delete role. Please try again.", "error");
      }
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

  if (loading && roles.length === 0) {
    return (
      <div className={styles.agentAssignmentContainer}>
        <Loader />
      </div>
    );
  }

  return (
    <div className={styles.agentAssignmentContainer}>
      {loading && <Loader />}

      {/* Header Row: Select Role Dropdown (left) and Create Role Button (right) */}
      <div className={styles.roleHeaderRow}>
        <div className={styles.roleDropdownContainer}>
          <label className={styles.controlLabel}>Select Role</label>
          <div className={styles.searchableDropdownSmall}>
            <div
              className={`${styles.dropdownTriggerSmall} ${showRoleDropdown ? styles.active : ""}`}
              onClick={handleRoleDropdownToggle}
              onKeyDown={handleRoleKeyDown}
              tabIndex={0}
              role="combobox"
              aria-expanded={showRoleDropdown}
              aria-haspopup="listbox"
              aria-controls="role-dropdown-list">
              <span>{selectedRole ? selectedRole.name || selectedRole.role_name : "Select Role"}</span>
              <svg
                width="18"
                height="18"
                viewBox="0 0 20 20"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                className={`${styles.chevronIcon} ${showRoleDropdown ? styles.rotated : ""}`}>
                <path d="M6 8L10 12L14 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            {showRoleDropdown && (
              <div className={styles.dropdownContent} onClick={(e) => e.stopPropagation()} id="role-dropdown-list" role="listbox">
                <div className={styles.searchContainer}>
                  <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={styles.searchIcon}>
                    <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" fill="none" />
                    <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  </svg>
                  <input
                    type="text"
                    placeholder="Search roles..."
                    value={roleSearchTerm}
                    onChange={(e) => setRoleSearchTerm(e.target.value)}
                    className={styles.searchInput}
                    autoComplete="off"
                  />
                </div>
                <div className={styles.agentsList}>
                  {filteredRoles.length > 0 ? (
                    filteredRoles.map((role, index) => (
                      <div
                        key={role.id || role.role_id || index}
                        data-role-index={index}
                        className={`${styles.agentItem} ${index === highlightedRoleIndex ? styles.highlighted : ""}`}
                        onClick={() => handleRoleSelection(role)}
                        onMouseEnter={() => setHighlightedRoleIndex(index)}
                        onMouseLeave={() => setHighlightedRoleIndex(-1)}
                        role="option"
                        aria-selected={index === highlightedRoleIndex}>
                        <div className={styles.agentName}>{role.name || role.role_name}</div>
                        <button
                          className={styles.deleteIcon}
                          onClick={(event) => handleDeleteClick(role, event)}
                          title="Delete Role"
                          aria-label={`Delete role ${role.name || role.role_name}`}>
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path
                              d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2M10 11v6M14 11v6"
                              stroke="currentColor"
                              strokeWidth="2"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          </svg>
                        </button>
                      </div>
                    ))
                  ) : (
                    <div className={styles.noAgents}>No roles found</div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
        <div className={styles.roleCreateButtonContainer}>
          <button onClick={() => setShowCreateRole(true)} className="iafButton iafButtonPrimary">
            Create Role
          </button>
        </div>
      </div>

      {/* Role Permissions Section - Show when a role is selected */}
      {selectedRole && <RolePermissionsSection selectedRole={selectedRole} />}

      {/* Create Role Modal */}
      <Modal
        isOpen={showCreateRole}
        onClose={() => {
          setShowCreateRole(false);
          setNewRoleName("");
        }}
        onResetForm={() => setNewRoleName("")}
        title="Create New Role">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleCreateRole();
          }}
          className={styles.topControls}>
          <div className={styles.controlGroup}>
            <label className={styles.controlLabel}>Role Name</label>
            <input
              type="text"
              value={newRoleName}
              onChange={(e) => setNewRoleName(e.target.value)}
              placeholder="Enter role name (e.g., Manager, Admin)"
              className={styles.searchInput}
              maxLength={50}
              autoFocus
            />
          </div>
          <div className={styles.modalFooter}>
            <div className={styles.buttonClass}>
              <button type="submit" className="iafButton iafButtonPrimary" disabled={createRoleLoading || !newRoleName.trim()}>
                {createRoleLoading ? "Creating..." : "Create Role"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowCreateRole(false);
                  setNewRoleName("");
                }}
                className="iafButton iafButtonSecondary">
                Cancel
              </button>
            </div>
          </div>
        </form>
      </Modal>

      {/* Add User to Role Modal */}
      {showAddUser && (
        <div className={styles.modalOverlay}>
          <div className={styles.modal}>
            <div className={styles.modalHeader}>
              <h3>Add User to Role: {selectedRole?.name || selectedRole?.role_name}</h3>
              <button
                className={styles.modalCloseButton}
                onClick={() => {
                  setShowAddUser(false);
                  setSelectedRole(null);
                  setUserSearchTerm("");
                }}>
                ×
              </button>
            </div>
            <div className={styles.modalBody}>
              <div className={styles.formGroup}>
                <label htmlFor="userEmail">User Email</label>
                <input
                  type="email"
                  id="userEmail"
                  value={userSearchTerm}
                  onChange={(e) => setUserSearchTerm(e.target.value)}
                  placeholder="Enter user email address"
                  className={styles.formInput}
                />
                <div className={styles.inputHint}>Enter the email address of the user you want to assign to this role.</div>
              </div>
            </div>
            <div className={styles.modalFooter}>
              <button
                type="button"
                className="iafButton iafButtonSecondary"
                onClick={() => {
                  setShowAddUser(false);
                  setSelectedRole(null);
                  setUserSearchTerm("");
                }}>
                Cancel
              </button>
              <button type="button" className="iafButton iafButtonPrimary" onClick={handleAssignUser} disabled={assignUserLoading || !userSearchTerm.trim()}>
                {assignUserLoading ? "Adding..." : "Add User"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Role Confirmation Modal (matching Group tab pattern) */}
      {showDeleteConfirmation && (
        <ConfirmationModal
          message={`Are you sure you want to delete the role "${
            roleToDelete?.name || roleToDelete?.role_name
          }"? This action cannot be undone and will remove all permissions associated with this role.`}
          onConfirm={handleConfirmDelete}
          setShowConfirmation={setShowDeleteConfirmation}
        />
      )}

      {loading && (
        <div className={styles.loadingOverlay}>
          <Loader />
        </div>
      )}
    </div>
  );
};

export default RoleAgentAssignment;
