import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import Cookies from "js-cookie";
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import { useMessage } from "../../Hooks/MessageContext";
import { extractErrorMessage } from "../../utils/errorUtils";
import Loader from "../commonComponents/Loader";
import EmptyState from "../commonComponents/EmptyState";
import Toggle from "../commonComponents/Toggle";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine";
import DisplayCard1 from "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1";
import TextField from "../../iafComponents/GlobalComponents/TextField/TextField";
import styles from "./ResourceAllocationManagement.module.css";

// Constants
const HTTP_NOT_FOUND = 404;
const HTTP_FORBIDDEN = 403;
const MAX_VALUES_DISPLAY = 2;

// Icon Components - Inline SVGs for better control
const KeyIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
  </svg>
);

const ChevronLeftIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="15,18 9,12 15,6" />
  </svg>
);

const UserPlusIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
    <circle cx="8.5" cy="7" r="4" />
    <line x1="20" y1="8" x2="20" y2="14" />
    <line x1="23" y1="11" x2="17" y2="11" />
  </svg>
);

// Icons moved to DisplayCard1 component

const CloseIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

const PlusIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="12" y1="5" x2="12" y2="19" />
    <line x1="5" y1="12" x2="19" y2="12" />
  </svg>
);

/**
 * ResourceAllocationManagement Component
 * 
 * Admin panel for managing user assignments to access keys.
 * Modern card-based layout with smooth transitions.
 * 
 * Based on Swagger endpoints:
 * - GET /resource-allocation/access-keys - List access keys
 * - GET /resource-allocation/access-keys/{access_key}/users - Get users
 * - PUT /resource-allocation/access-keys/{access_key}/users/{user_email}/access - Add/Update user
 * - DELETE /resource-allocation/access-keys/{access_key}/users/{user_email} - Remove user
 * - POST /resource-allocation/access-keys/{access_key}/bulk-assign - Bulk assign
 * - DELETE /resource-allocation/access-keys/{access_key} - Delete access key
 */
const ResourceAllocationManagement = ({ externalSearchTerm = "", onPlusClickRef, onClearSearchRef, onNavigationChange }) => {
  // State
  const [accessKeys, setAccessKeys] = useState([]);
  const [selectedKey, setSelectedKey] = useState(null);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [usersLoading, setUsersLoading] = useState(false);
  const [selectedUsers, setSelectedUsers] = useState([]);
  const [userSearchTerm, setUserSearchTerm] = useState("");

  // Modal states
  const [showAddUserModal, setShowAddUserModal] = useState(false);
  const [showBulkAssignModal, setShowBulkAssignModal] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [actionLoading, setActionLoading] = useState(false);

  // Hooks
  const { fetchData, postData, putData, deleteData } = useFetch();
  const { addMessage } = useMessage();

  // Use ref for addMessage to avoid infinite loops in useCallback
  const addMessageRef = useRef(addMessage);
  useEffect(() => {
    addMessageRef.current = addMessage;
  }, [addMessage]);

  // Notify parent of navigation state changes (for hiding SubHeader in detail view)
  useEffect(() => {
    if (onNavigationChange) {
      onNavigationChange({
        isDetailView: Boolean(selectedKey),
        keyName: selectedKey?.access_key || null,
      });
    }
  }, [selectedKey, onNavigationChange]);

  // User role
  const role = Cookies.get("role") || "";
  const isAdmin = role.toLowerCase() === "admin" || role.toLowerCase() === "superadmin" || role.toLowerCase() === "super_admin";

  // Disable plus button - no create endpoint
  useEffect(() => {
    if (onPlusClickRef) {
      onPlusClickRef.current = null;
    }
  }, [onPlusClickRef]);

  // Clear search handler
  useEffect(() => {
    if (onClearSearchRef) {
      onClearSearchRef.current = () => {
        setSelectedKey(null);
      };
    }
  }, [onClearSearchRef]);

  /**
   * Fetch all access keys
   */
  const fetchAccessKeys = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchData(APIs.GET_ACCESS_KEYS);

      // Debug: log response to see actual field names
      console.log("Access Keys API Response:", response);

      // Handle various response formats
      let data = [];
      if (Array.isArray(response)) {
        data = response;
      } else if (response?.access_keys && Array.isArray(response.access_keys)) {
        data = response.access_keys;
      } else if (response?.data && Array.isArray(response.data)) {
        data = response.data;
      } else if (response?.details && Array.isArray(response.details)) {
        data = response.details;
      }

      // Debug: log parsed data to see available fields
      if (data.length > 0) {
        console.log("Access Key fields available:", Object.keys(data[0]), data[0]);
      }

      setAccessKeys(data);
    } catch (error) {
      console.error("Error fetching access keys:", error);
      const errorMessage = extractErrorMessage(error).message || "Failed to fetch access keys";
      addMessageRef.current(errorMessage, "error");
      setAccessKeys([]);
    } finally {
      setLoading(false);
    }
  }, [fetchData]);

  /**
   * Fetch users for selected access key
   */
  const fetchUsers = useCallback(async (accessKey) => {
    if (!accessKey) return;

    setUsersLoading(true);
    try {
      const url = `${APIs.GET_ACCESS_KEY_USERS}${encodeURIComponent(accessKey)}/users`;
      const response = await fetchData(url);
      const data = response?.users || response || [];
      setUsers(Array.isArray(data) ? data : []);
    } catch (error) {
      console.error("Error fetching users:", error);
      const status = error?.response?.status;
      // 404 means no users yet - not an error
      // 403 means permission denied - show message but don't block
      if (status === HTTP_FORBIDDEN) {
        addMessageRef.current("Permission denied: Unable to view users for this access key", "error");
      } else if (status !== HTTP_NOT_FOUND) {
        const errorMessage = extractErrorMessage(error).message || "Failed to fetch users";
        addMessageRef.current(errorMessage, "error");
      }
      setUsers([]);
    } finally {
      setUsersLoading(false);
    }
  }, [fetchData]);

  /**
   * Fetch specific user's values and exclusions for an access key
   * Uses: GET /resource-allocation/access-keys/{access_key}/users/{user_email}
   */
  const fetchUserValues = useCallback(async (accessKey, userEmail) => {
    try {
      const url = `${APIs.GET_USER_VALUES}${encodeURIComponent(accessKey)}/users/${encodeURIComponent(userEmail)}`;
      const response = await fetchData(url);
      // Response contains values/allowed_values and exclusions/excluded_values
      const values = response?.values || response?.allowed_values || [];
      const exclusions = response?.exclusions || response?.excluded_values || [];
      return {
        values: Array.isArray(values) ? values : [],
        exclusions: Array.isArray(exclusions) ? exclusions : []
      };
    } catch (error) {
      console.error("Error fetching user values:", error);
      return { values: [], exclusions: [] };
    }
  }, [fetchData]);

  /**
   * Open edit modal and fetch user's current values and exclusions
   */
  const openEditModal = useCallback(async (user) => {
    const email = user.user_email || user.email || user.id;
    if (!selectedKey || !email) return;

    setActionLoading(true);
    const { values, exclusions } = await fetchUserValues(selectedKey.access_key, email);
    setEditingUser({ ...user, user_email: email, values, exclusions });
    setActionLoading(false);
  }, [selectedKey, fetchUserValues]);

  // Initial load - only fetch access keys
  useEffect(() => {
    fetchAccessKeys();
  }, [fetchAccessKeys]);

  // Fetch users when key is selected
  useEffect(() => {
    if (selectedKey) {
      fetchUsers(selectedKey.access_key);
      setSelectedUsers([]);
    }
  }, [selectedKey, fetchUsers]);

  /**
   * Filter access keys by search
   */
  const filteredKeys = useMemo(() => {
    if (!externalSearchTerm.trim()) return accessKeys;
    const search = externalSearchTerm.toLowerCase();
    return accessKeys.filter(key =>
      (key.access_key || "").toLowerCase().includes(search) ||
      (key.description || "").toLowerCase().includes(search)
    );
  }, [accessKeys, externalSearchTerm]);

  /**
   * Handle access key click
   */
  const handleKeyClick = (key) => {
    setSelectedKey(key);
  };

  /**
   * Handle back button
   */
  const handleBack = () => {
    setSelectedKey(null);
    setUsers([]);
    setSelectedUsers([]);
  };

  /**
   * Handle delete access key - called after user confirms on card flip
   */
  const handleDeleteKey = async (key) => {
    try {
      await deleteData(`${APIs.DELETE_ACCESS_KEY}${encodeURIComponent(key.access_key)}`);
      addMessage("Access key deleted", "success");
      if (selectedKey?.access_key === key.access_key) {
        setSelectedKey(null);
      }
      fetchAccessKeys();
    } catch (error) {
      addMessage(extractErrorMessage(error).message || "Failed to delete access key", "error");
    }
  };

  /**
   * Handle add user to access key with values and exclusions
   */
  const handleAddUser = async (userEmail, values = [], exclusions = []) => {
    if (!selectedKey || !userEmail) return;

    setActionLoading(true);
    try {
      const url = `${APIs.UPDATE_USER_ACCESS}${encodeURIComponent(selectedKey.access_key)}/users/${encodeURIComponent(userEmail)}/access`;
      await putData(url, { add_values: values, add_exclusions: exclusions });
      addMessage("User added successfully", "success");
      setShowAddUserModal(false);
      fetchUsers(selectedKey.access_key);
    } catch (error) {
      addMessage(extractErrorMessage(error).message || "Failed to add user", "error");
    } finally {
      setActionLoading(false);
    }
  };

  /**
   * Handle update user values and exclusions
   */
  const handleUpdateUser = async (userEmail, newValues, oldValues = [], newExclusions = [], oldExclusions = []) => {
    if (!selectedKey || !userEmail) return;

    const addValues = newValues.filter(v => !oldValues.includes(v));
    const removeValues = oldValues.filter(v => !newValues.includes(v));
    const addExclusions = newExclusions.filter(v => !oldExclusions.includes(v));
    const removeExclusions = oldExclusions.filter(v => !newExclusions.includes(v));

    setActionLoading(true);
    try {
      const url = `${APIs.UPDATE_USER_ACCESS}${encodeURIComponent(selectedKey.access_key)}/users/${encodeURIComponent(userEmail)}/access`;
      await putData(url, {
        add_values: addValues,
        remove_values: removeValues,
        add_exclusions: addExclusions,
        remove_exclusions: removeExclusions
      });
      addMessage("User updated successfully", "success");
      setEditingUser(null);
      fetchUsers(selectedKey.access_key);
    } catch (error) {
      addMessage(extractErrorMessage(error).message || "Failed to update user", "error");
    } finally {
      setActionLoading(false);
    }
  };

  /**
   * Handle remove user from access key - called after user confirms on card flip
   */
  const handleRemoveUser = async (userEmail) => {
    if (!selectedKey || !userEmail) return;

    setActionLoading(true);
    try {
      const url = `${APIs.REMOVE_USER_FROM_ACCESS_KEY}${encodeURIComponent(selectedKey.access_key)}/users/${encodeURIComponent(userEmail)}`;
      await deleteData(url);
      addMessage("User removed", "success");
      setSelectedUsers(prev => prev.filter(e => e !== userEmail));
      fetchUsers(selectedKey.access_key);
    } catch (error) {
      addMessage(extractErrorMessage(error).message || "Failed to remove user", "error");
    } finally {
      setActionLoading(false);
    }
  };

  /**
   * Handle bulk assign values
   */
  const handleBulkAssign = async (values) => {
    if (!selectedKey || selectedUsers.length === 0 || values.length === 0) return;

    setActionLoading(true);
    try {
      const url = `${APIs.BULK_ASSIGN_VALUES}${encodeURIComponent(selectedKey.access_key)}/bulk-assign`;
      await postData(url, { user_emails: selectedUsers, add_values: values });
      addMessage(`Values assigned to ${selectedUsers.length} user(s)`, "success");
      setShowBulkAssignModal(false);
      setSelectedUsers([]);
      fetchUsers(selectedKey.access_key);
    } catch (error) {
      addMessage(extractErrorMessage(error).message || "Failed to bulk assign", "error");
    } finally {
      setActionLoading(false);
    }
  };

  /**
   * Toggle user selection
   */
  const toggleUserSelection = (email) => {
    setSelectedUsers(prev =>
      prev.includes(email) ? prev.filter(e => e !== email) : [...prev, email]
    );
  };

  /**
   * Open add user modal
   */
  const openAddUserModal = () => {
    setShowAddUserModal(true);
  };

  // Loading state shown inline
  const isInitialLoading = loading;

  return (
    <div className={styles.container}>
      {isInitialLoading && <Loader />}
      {/* Add User Modal */}
      {showAddUserModal && (
        <AddUserModalInline
          onClose={() => setShowAddUserModal(false)}
          onSubmit={handleAddUser}
          loading={actionLoading}
          keyName={selectedKey?.access_key}
        />
      )}

      {/* Bulk Assign Modal */}
      {showBulkAssignModal && (
        <BulkAssignModalInline
          selectedCount={selectedUsers.length}
          onClose={() => setShowBulkAssignModal(false)}
          onSubmit={handleBulkAssign}
          loading={actionLoading}
        />
      )}

      {/* Edit User Modal */}
      {editingUser && (
        <EditUserModalInline
          user={editingUser}
          onClose={() => setEditingUser(null)}
          onSubmit={(newValues, newExclusions) => handleUpdateUser(
            editingUser.user_email || editingUser.email,
            newValues,
            editingUser.values || [],
            newExclusions,
            editingUser.exclusions || []
          )}
          loading={actionLoading}
        />
      )}

      {/* Access Keys Grid View */}
      {!selectedKey && (
        <>
          <div className="listWrapper">
            {filteredKeys.length > 0 ? (
              <DisplayCard1
                data={filteredKeys.map(key => ({
                  ...key,
                  id: key.access_key,
                  name: key.access_key,
                  access_key: key.access_key,
                  description: key.description || "",
                  category: key.type || key.key_type || "Access Key"
                }))}
                onCardClick={(cardName, item) => handleKeyClick(item)}
                {...(isAdmin && { onDeleteClick: (cardName, item) => handleDeleteKey(item) })}
                showDeleteButton={isAdmin}
                cardNameKey="name"
                cardDescriptionKey="description"
                cardCategoryKey="category"
                contextType="resource"
                showCreateCard={false}
                showCheckbox={false}
                className="resource-cards"
              />
            ) : (
              <EmptyState
                message="No access keys found"
                subMessage="Access keys are configured in the Resource Dashboard"
              />
            )}
          </div>
        </>
      )}

      {/* Users Detail View */}
      {selectedKey && (
        <div className={styles.detailSection}>
          {/* Info Bar - Shows key name and actions */}
          <div className={styles.infoBar}>
            <div className={styles.infoBarLeft}>
              <button className={styles.backBtn} onClick={handleBack} aria-label="Go back">
                <ChevronLeftIcon />
              </button>
              <span className={styles.keyName}>{selectedKey.access_key}</span>
            </div>
            {isAdmin && (
              <div className={styles.actionButtons}>
                <div className={styles.searchFieldWrapper}>
                  <TextField
                    placeholder="Search"
                    value={userSearchTerm}
                    onChange={(e) => setUserSearchTerm(e.target.value)}
                    onClear={() => setUserSearchTerm("")}
                    showClearButton={true}
                    showSearchButton={true}
                    aria-label="Search users"
                  />
                </div>
                {selectedUsers.length > 0 ? (
                  <button className={styles.assignValuesBtn} onClick={() => setShowBulkAssignModal(true)}>
                    <PlusIcon />
                    Assign Values
                  </button>
                ) : (
                  <button className={styles.addUserBtn} onClick={openAddUserModal}>
                    <UserPlusIcon />
                    Add User
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Selection Bar - Select All & Items Count */}
          {!usersLoading && users.length > 0 && isAdmin && (
            <div className={styles.selectionBar}>
              <label className={styles.selectAllLabel}>
                <input
                  type="checkbox"
                  checked={selectedUsers.length === users.filter(u => {
                    if (!userSearchTerm) return true;
                    const email = u.user_email || u.email || "";
                    const name = u.name || u.user_name || email.split("@")[0] || "";
                    const searchLower = userSearchTerm.toLowerCase();
                    return name.toLowerCase().includes(searchLower) || email.toLowerCase().includes(searchLower);
                  }).length && users.length > 0}
                  onChange={(e) => {
                    const filteredUsers = users.filter(u => {
                      if (!userSearchTerm) return true;
                      const email = u.user_email || u.email || "";
                      const name = u.name || u.user_name || email.split("@")[0] || "";
                      const searchLower = userSearchTerm.toLowerCase();
                      return name.toLowerCase().includes(searchLower) || email.toLowerCase().includes(searchLower);
                    });
                    if (e.target.checked) {
                      // Select all filtered users
                      setSelectedUsers(filteredUsers.map(u => u.user_email || u.email));
                    } else {
                      // Deselect all
                      setSelectedUsers([]);
                    }
                  }}
                  className={styles.selectAllCheckbox}
                />
                Select All
              </label>
              <span className={styles.itemsCount}>
                Showing items {users.filter(u => {
                  if (!userSearchTerm) return true;
                  const email = u.user_email || u.email || "";
                  const name = u.name || u.user_name || email.split("@")[0] || "";
                  const searchLower = userSearchTerm.toLowerCase();
                  return name.toLowerCase().includes(searchLower) || email.toLowerCase().includes(searchLower);
                }).length} of {users.length}
              </span>
            </div>
          )}

          {/* Users Loading */}
          {usersLoading && (
            <div className={styles.loadingOverlay}>
              <Loader />
            </div>
          )}

          {/* Users Grid */}
          {!usersLoading && users.length > 0 && (
            <div className="listWrapper">
              <DisplayCard1
                data={users.filter(user => {
                  if (!userSearchTerm) return true;
                  const email = user.user_email || user.email || "";
                  const name = user.name || user.user_name || email.split("@")[0] || "";
                  const searchLower = userSearchTerm.toLowerCase();
                  return name.toLowerCase().includes(searchLower) || email.toLowerCase().includes(searchLower);
                }).map(user => {
                  const email = user.user_email || user.email;
                  const name = user.name || user.user_name || email?.split("@")[0] || "User";
                  return {
                    ...user,
                    id: email,
                    name: name,
                    description: email,
                    category: "User"
                  };
                })}
                {...(isAdmin && {
                  onCardClick: (cardName, item) => {
                    // Open edit modal - fetches values from API
                    openEditModal(item);
                  },
                  onDeleteClick: (cardName, item) => handleRemoveUser(item.id),
                  onSelectionChange: (name, checked, item) => {
                    // Find the user by name to get their full email
                    const user = users.find(u => {
                      const email = u.user_email || u.email;
                      const displayName = u.name || u.user_name || email?.split("@")[0] || "User";
                      return displayName === name || email === name;
                    });
                    const userEmail = user ? (user.user_email || user.email) : name;
                    toggleUserSelection(userEmail);
                  }
                })}
                showEditButton={false}
                showDeleteButton={isAdmin}
                cardNameKey="name"
                cardDescriptionKey="description"
                cardCategoryKey="category"
                contextType="user"
                showCreateCard={false}
                showCheckbox={isAdmin}
                selectedIds={selectedUsers}
                idKey="id"
              />
            </div>
          )}

          {/* Empty State */}
          {!usersLoading && users.length === 0 && (
            <EmptyState
              message="No users assigned"
              subMessage={isAdmin ? "Click 'Add User' to grant access to this key" : "No users have been assigned yet"}
            />
          )}
        </div>
      )}
    </div>
  );
};

/**
 * Inline Add User Modal - Supports both include values and exclusions with toggle
 */
const AddUserModalInline = ({ onClose, onSubmit, loading, keyName }) => {
  const [email, setEmail] = useState("");
  const [values, setValues] = useState([]);
  const [exclusions, setExclusions] = useState([]);
  const [newValue, setNewValue] = useState("");
  const [newExclusion, setNewExclusion] = useState("");
  // Toggle state for "Include All Values" mode
  const [includeAllValues, setIncludeAllValues] = useState(false);
  // Preserve values before enabling "Include All Values" toggle
  const [preservedValues, setPreservedValues] = useState([]);

  const addValue = () => {
    const v = newValue.trim();
    if (v && !values.includes(v)) {
      setValues([...values, v]);
      setNewValue("");
    }
  };

  const removeValue = (v) => setValues(values.filter(x => x !== v));

  const addExclusion = () => {
    const v = newExclusion.trim();
    if (v && !exclusions.includes(v)) {
      setExclusions([...exclusions, v]);
      setNewExclusion("");
    }
  };

  const removeExclusion = (v) => setExclusions(exclusions.filter(x => x !== v));

  // Handle toggle for "Include All Values"
  const handleToggleChange = (newState) => {
    setIncludeAllValues(newState);
    if (newState) {
      // When enabling, preserve current values and set to ["*"]
      setPreservedValues(values.filter(v => v !== "*"));
      setValues(["*"]);
      setNewValue("");
    } else {
      // When disabling, restore preserved values and clear exclusions
      setValues(preservedValues);
      setExclusions([]);
      setNewExclusion("");
    }
  };

  const handleSubmit = () => {
    const trimmedEmail = email.trim();
    if (trimmedEmail) {
      onSubmit(trimmedEmail, values, exclusions);
    }
  };

  // Basic email validation
  const isValidEmail = email.trim() && email.includes("@");

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modalContainer} onClick={e => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <h3 className={styles.modalTitle}>Add User - {keyName}</h3>
          <button className={styles.modalCloseBtn} onClick={onClose} aria-label="Close">
            <CloseIcon />
          </button>
        </div>
        <div className={styles.modalBody}>
          <div className={styles.formField}>
            <label className={styles.fieldLabel}>User Email <span className={styles.required}>*</span></label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="Enter user email..."
              className={styles.textInput}
              autoFocus
            />
          </div>

          {/* Include Values Section */}
          <div className={styles.formField}>
            <label className={styles.fieldLabel}>Include Values</label>
            {includeAllValues ? (
              // Show * indicator when Include All Values is enabled
              <div className={styles.chipContainer}>
                <span className={styles.chip}>*</span>
              </div>
            ) : (
              <>
                <div className={styles.inputWithButton}>
                  <input
                    type="text"
                    placeholder="Add include value..."
                    value={newValue}
                    onChange={e => setNewValue(e.target.value)}
                    onKeyDown={e => e.key === "Enter" && (e.preventDefault(), addValue())}
                    className={styles.textInput}
                  />
                  <button
                    className={styles.addValueBtn}
                    onClick={addValue}
                    disabled={!newValue.trim()}
                    type="button"
                  >
                    <PlusIcon />
                    Add
                  </button>
                </div>
                {values.length > 0 && (
                  <div className={styles.chipContainer}>
                    {values.map((v, i) => (
                      <span key={i} className={styles.chip}>
                        {v}
                        <button onClick={() => removeValue(v)} className={styles.chipRemove}>×</button>
                      </span>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>

          {/* Exclude Values Section - Only show when Include All Values is enabled */}
          {includeAllValues && (
            <div className={styles.formField}>
              <label className={styles.fieldLabel}>Exclude Values</label>
              <div className={styles.inputWithButton}>
                <input
                  type="text"
                  placeholder="Add exclude value..."
                  value={newExclusion}
                  onChange={e => setNewExclusion(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && (e.preventDefault(), addExclusion())}
                  className={styles.textInput}
                />
                <button
                  className={styles.addValueBtn}
                  onClick={addExclusion}
                  disabled={!newExclusion.trim()}
                  type="button"
                >
                  <PlusIcon />
                  Add
                </button>
              </div>
              {exclusions.length > 0 && (
                <div className={styles.chipContainer}>
                  {exclusions.map((v, i) => (
                    <span key={i} className={styles.chip}>
                      {v}
                      <button onClick={() => removeExclusion(v)} className={styles.chipRemove}>×</button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
        <div className={styles.modalFooter}>
          {/* Include All Values Toggle on the left */}
          <div className={styles.toggleContainer}>
            <Toggle
              value={includeAllValues}
              onChange={(e) => handleToggleChange(e.target.checked)}
              disabled={loading}
            />
            <span className={styles.toggleText}>Include All Values</span>
          </div>
          {/* Buttons on the right */}
          <div className={styles.footerButtons}>
            <button className={styles.secondaryBtn} onClick={onClose} disabled={loading}>
              Cancel
            </button>
            <button
              className={styles.primaryBtn}
              onClick={handleSubmit}
              disabled={loading || !isValidEmail}
            >
              {loading ? "Adding..." : "Add User"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

/**
 * Inline Edit User Modal - Supports both include values and exclusions with toggle
 */
const EditUserModalInline = ({ user, onClose, onSubmit, loading }) => {
  // Initialize values - check if user has "*" (include all) pattern
  const initialValues = user.values || [];
  const hasWildcard = initialValues.includes("*");

  const [values, setValues] = useState(initialValues);
  const [exclusions, setExclusions] = useState(user.exclusions || []);
  const [newValue, setNewValue] = useState("");
  const [newExclusion, setNewExclusion] = useState("");
  // Toggle state for "Include All Values" mode - initialize based on existing data
  const [includeAllValues, setIncludeAllValues] = useState(hasWildcard || (user.exclusions && user.exclusions.length > 0));
  // Preserve values before enabling "Include All Values" toggle
  const [preservedValues, setPreservedValues] = useState(hasWildcard ? [] : initialValues.filter(v => v !== "*"));

  const userEmail = user.user_email || user.email;
  const userName = user.name || user.user_name || userEmail?.split("@")[0] || "User";

  const addValue = () => {
    const v = newValue.trim();
    if (v && !values.includes(v)) {
      setValues([...values, v]);
      setNewValue("");
    }
  };

  const removeValue = (v) => setValues(values.filter(x => x !== v));

  const addExclusion = () => {
    const v = newExclusion.trim();
    if (v && !exclusions.includes(v)) {
      setExclusions([...exclusions, v]);
      setNewExclusion("");
    }
  };

  const removeExclusion = (v) => setExclusions(exclusions.filter(x => x !== v));

  // Handle toggle for "Include All Values"
  const handleToggleChange = (newState) => {
    setIncludeAllValues(newState);
    if (newState) {
      // When enabling, preserve current values and set to ["*"]
      setPreservedValues(values.filter(v => v !== "*"));
      setValues(["*"]);
      setNewValue("");
    } else {
      // When disabling, restore preserved values and clear exclusions
      setValues(preservedValues);
      setExclusions([]);
      setNewExclusion("");
    }
  };

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modalContainer} onClick={e => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <h3 className={styles.modalTitle}>Edit Access - {userName}</h3>
          <button className={styles.modalCloseBtn} onClick={onClose} aria-label="Close">
            <CloseIcon />
          </button>
        </div>
        <div className={styles.modalBody}>
          {/* Include Values Section */}
          <div className={styles.formField}>
            <label className={styles.fieldLabel}>Include Values</label>
            {includeAllValues ? (
              // Show * indicator when Include All Values is enabled
              <div className={styles.chipContainer}>
                <span className={styles.chip}>*</span>
              </div>
            ) : (
              <>
                <div className={styles.inputWithButton}>
                  <input
                    type="text"
                    placeholder="Add include value..."
                    value={newValue}
                    onChange={e => setNewValue(e.target.value)}
                    onKeyDown={e => e.key === "Enter" && (e.preventDefault(), addValue())}
                    className={styles.textInput}
                  />
                  <button
                    className={styles.addValueBtn}
                    onClick={addValue}
                    disabled={!newValue.trim()}
                    type="button"
                  >
                    <PlusIcon />
                    Add
                  </button>
                </div>
                {values.length > 0 ? (
                  <div className={styles.chipContainer}>
                    {values.map((v, i) => (
                      <span key={i} className={styles.chip}>
                        {v}
                        <button onClick={() => removeValue(v)} className={styles.chipRemove}>×</button>
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className={styles.emptyFieldText}>No values assigned yet</p>
                )}
              </>
            )}
          </div>

          {/* Exclude Values Section - Only show when Include All Values is enabled */}
          {includeAllValues && (
            <div className={styles.formField}>
              <label className={styles.fieldLabel}>Exclude Values</label>
              <div className={styles.inputWithButton}>
                <input
                  type="text"
                  placeholder="Add exclude value..."
                  value={newExclusion}
                  onChange={e => setNewExclusion(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && (e.preventDefault(), addExclusion())}
                  className={styles.textInput}
                />
                <button
                  className={styles.addValueBtn}
                  onClick={addExclusion}
                  disabled={!newExclusion.trim()}
                  type="button"
                >
                  <PlusIcon />
                  Add
                </button>
              </div>
              {exclusions.length > 0 ? (
                <div className={styles.chipContainer}>
                  {exclusions.map((v, i) => (
                    <span key={i} className={styles.chip}>
                      {v}
                      <button onClick={() => removeExclusion(v)} className={styles.chipRemove}>×</button>
                    </span>
                  ))}
                </div>
              ) : (
                <p className={styles.emptyFieldText}>No exclusions set</p>
              )}
            </div>
          )}
        </div>
        <div className={styles.modalFooter}>
          {/* Include All Values Toggle on the left */}
          <div className={styles.toggleContainer}>
            <Toggle
              value={includeAllValues}
              onChange={(e) => handleToggleChange(e.target.checked)}
              disabled={loading}
            />
            <span className={styles.toggleText}>Include All Values</span>
          </div>
          {/* Buttons on the right */}
          <div className={styles.footerButtons}>
            <button className={styles.secondaryBtn} onClick={onClose} disabled={loading}>
              Cancel
            </button>
            <button className={styles.primaryBtn} onClick={() => onSubmit(values, exclusions)} disabled={loading}>
              {loading ? "Saving..." : "Save Changes"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

/**
 * Inline Bulk Assign Modal
 */
const BulkAssignModalInline = ({ selectedCount, onClose, onSubmit, loading }) => {
  const [values, setValues] = useState([]);
  const [newValue, setNewValue] = useState("");

  const addValue = () => {
    const v = newValue.trim();
    if (v && !values.includes(v)) {
      setValues([...values, v]);
      setNewValue("");
    }
  };

  const removeValue = (v) => setValues(values.filter(x => x !== v));

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modalContainer} onClick={e => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <h3 className={styles.modalTitle}>Bulk Assign Values ({selectedCount} users)</h3>
          <button className={styles.modalCloseBtn} onClick={onClose} aria-label="Close">
            <CloseIcon />
          </button>
        </div>
        <div className={styles.modalBody}>
          <div className={styles.infoCard}>
            <span className={styles.infoIcon}>ℹ️</span>
            <span>These values will be added to all selected users.</span>
          </div>
          <div className={styles.formField}>
            <label className={styles.fieldLabel}>Values to Assign <span className={styles.required}>*</span></label>
            <div className={styles.inputWithButton}>
              <input
                type="text"
                placeholder="Enter a value..."
                value={newValue}
                onChange={e => setNewValue(e.target.value)}
                onKeyDown={e => e.key === "Enter" && (e.preventDefault(), addValue())}
                className={styles.textInput}
              />
              <button
                className={styles.addValueBtn}
                onClick={addValue}
                disabled={!newValue.trim()}
                type="button"
              >
                <PlusIcon />
                Add
              </button>
            </div>
            {values.length > 0 && (
              <div className={styles.chipContainer}>
                {values.map((v, i) => (
                  <span key={i} className={styles.chip}>
                    {v}
                    <button onClick={() => removeValue(v)} className={styles.chipRemove}>×</button>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className={styles.modalFooter}>
          <button className={styles.secondaryBtn} onClick={onClose} disabled={loading}>
            Cancel
          </button>
          <button
            className={styles.primaryBtn}
            onClick={() => onSubmit(values)}
            disabled={loading || values.length === 0}
          >
            {loading ? "Assigning..." : `Assign to ${selectedCount} User${selectedCount !== 1 ? "s" : ""}`}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ResourceAllocationManagement;
