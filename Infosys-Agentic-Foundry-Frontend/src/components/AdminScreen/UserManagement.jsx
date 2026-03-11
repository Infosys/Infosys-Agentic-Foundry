import React, { useState, useEffect, useCallback, useImperativeHandle, forwardRef } from "react";
import Cookies from "js-cookie";
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import { useMessage } from "../../Hooks/MessageContext";
import Toggle from "../commonComponents/Toggle";
import Loader from "../commonComponents/Loader";
import EmptyState from "../commonComponents/EmptyState";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import SVGIcons from "../../Icons/SVGIcons";
import styles from "./UserManagement.module.css";
import "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1.css";

/**
 * UserManagement Component
 * 
 * Card-based layout matching Tools/Servers/Agents pages.
 * Admin: Shows Active toggle (for logged-in department only)
 * SuperAdmin: Shows department dropdown + both Global and Active toggles
 * 
 * Exposes renderDepartmentDropdown via ref for parent to render next to search
 */
const UserManagement = forwardRef(({ externalSearchTerm = "", onReady }, ref) => {
  const loggedInDepartment = Cookies.get("department") || "";
  const userRole = Cookies.get("role") || "";
  const isSuperAdmin = userRole.toLowerCase() === "superadmin" || userRole.toLowerCase() === "super_admin";

  // State
  const [users, setUsers] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [selectedDepartment, setSelectedDepartment] = useState(loggedInDepartment);
  const [loading, setLoading] = useState(false);
  const [loadingDepartments, setLoadingDepartments] = useState(false);

  // Hooks
  const { fetchData, patchData } = useFetch();
  const { addMessage } = useMessage();

  /**
   * Fetch departments list (SuperAdmin only)
   */
  const fetchDepartments = useCallback(async () => {
    if (!isSuperAdmin) return;

    setLoadingDepartments(true);
    try {
      const response = await fetchData(APIs.GET_DEPARTMENTS_LIST);
      if (Array.isArray(response)) {
        setDepartments(response);
        // If no department selected yet, select the first one
        if (!selectedDepartment && response.length > 0) {
          setSelectedDepartment(response[0].department_name || response[0]);
        }
      } else if (response?.departments && Array.isArray(response.departments)) {
        setDepartments(response.departments);
        if (!selectedDepartment && response.departments.length > 0) {
          setSelectedDepartment(response.departments[0].department_name || response.departments[0]);
        }
      }
    } catch (error) {
      console.error("Failed to fetch departments:", error);
    } finally {
      setLoadingDepartments(false);
    }
  }, [isSuperAdmin, fetchData, selectedDepartment]);

  /**
   * Fetch users for the selected department
   */
  const fetchUsers = useCallback(async () => {
    if (!selectedDepartment) {
      setUsers([]);
      return;
    }

    setLoading(true);
    try {
      const endpoint = APIs.GET_DEPARTMENT_USERS.replace("{department_name}", encodeURIComponent(selectedDepartment));
      const response = await fetchData(endpoint);

      if (response?.users && Array.isArray(response.users)) {
        setUsers(response.users);
      } else if (Array.isArray(response)) {
        setUsers(response);
      } else {
        setUsers([]);
      }
    } catch (error) {
      addMessage("Failed to fetch users", "error");
      setUsers([]);
    } finally {
      setLoading(false);
    }
  }, [selectedDepartment, fetchData, addMessage]);

  // Fetch departments on mount for SuperAdmin
  useEffect(() => {
    if (isSuperAdmin) {
      fetchDepartments();
    }
  }, [isSuperAdmin, fetchDepartments]);

  // Fetch users when department changes
  useEffect(() => {
    if (selectedDepartment) {
      fetchUsers();
    }
  }, [selectedDepartment, fetchUsers]);

  /**
   * Handle Active toggle (department-level)
   * Sends: { email_id, is_active, global_is_active, department_name }
   */
  const handleActiveToggle = async (user) => {
    const newValue = !user.is_active;

    // Optimistic update
    setUsers(prevUsers =>
      prevUsers.map(u =>
        u.email === user.email ? { ...u, is_active: newValue } : u
      )
    );

    try {
      await patchData(APIs.SET_USER_ACTIVE_STATUS, {
        email_id: user.email,
        is_active: newValue,
        global_is_active: user.global_is_active,
        department_name: selectedDepartment || null
      });
      addMessage(`User ${newValue ? "activated" : "deactivated"} in ${selectedDepartment}`, "success");
    } catch (error) {
      // Revert on error
      setUsers(prevUsers =>
        prevUsers.map(u =>
          u.email === user.email ? { ...u, is_active: !newValue } : u
        )
      );
      const errorMessage = error?.response?.data?.detail || error?.message || "Failed to update user status";
      addMessage(errorMessage, "error");
    }
  };

  /**
   * Handle Global toggle (system-wide) - SuperAdmin only
   * Sends: { email_id, is_active } (no department_name or global_is_active when global toggle is on)
   */
  const handleGlobalToggle = async (user) => {
    const newValue = !user.global_is_active;

    // Optimistic update
    setUsers(prevUsers =>
      prevUsers.map(u =>
        u.email === user.email ? { ...u, global_is_active: newValue } : u
      )
    );

    try {
      await patchData(APIs.SET_USER_ACTIVE_STATUS, {
        email_id: user.email,
        is_active: newValue
      });
      addMessage(`User globally ${newValue ? "enabled" : "disabled"}`, "success");
    } catch (error) {
      // Revert on error
      setUsers(prevUsers =>
        prevUsers.map(u =>
          u.email === user.email ? { ...u, global_is_active: !newValue } : u
        )
      );
      const errorMessage = error?.response?.data?.detail || error?.message || "Failed to update global status";
      addMessage(errorMessage, "error");
    }
  };


  /**
   * Filter users based on search term
   */
  const filteredUsers = React.useMemo(() => {
    if (!externalSearchTerm.trim()) return users;
    const searchLower = externalSearchTerm.toLowerCase().trim();
    return users.filter(
      (user) =>
        (user.user_name && user.user_name.toLowerCase().includes(searchLower)) ||
        (user.email && user.email.toLowerCase().includes(searchLower)) ||
        (user.role && user.role.toLowerCase().includes(searchLower))
    );
  }, [users, externalSearchTerm]);

  /**
   * Get role badge class
   */
  const getRoleClass = (role) => {
    const roleLower = (role || "").toLowerCase();
    if (roleLower === "superadmin" || roleLower === "super_admin") return styles.roleSuperAdmin;
    if (roleLower === "admin") return styles.roleAdmin;
    if (roleLower === "developer") return styles.roleDeveloper;
    if (roleLower === "manager") return styles.roleManager;
    return styles.roleDefault;
  };

  /**
   * Get department name helper
   */
  const getDepartmentName = (dept) => {
    if (typeof dept === "string") return dept;
    return dept?.department_name || dept?.name || "";
  };

  /**
   * Transform departments to dropdown options format
   */
  const departmentOptions = departments.map(dept => getDepartmentName(dept));

  /**
   * Expose department dropdown render function to parent via ref
   */
  useImperativeHandle(ref, () => ({
    getDepartmentDropdown: () => {
      if (!isSuperAdmin) return null;
      return (
        <NewCommonDropdown
          options={departmentOptions}
          selected={selectedDepartment}
          onSelect={(value) => setSelectedDepartment(value)}
          placeholder="Select Department"
          showSearch={true}
          width="200px"
        />
      );
    },
    isSuperAdmin
  }), [isSuperAdmin, departmentOptions, selectedDepartment]);

  // Notify parent when component is ready (has mounted and ref is available)
  // Also notify when departments load so parent re-renders with dropdown
  useEffect(() => {
    if (onReady) {
      onReady();
    }
  }, [onReady, departmentOptions]);

  return (
    <div className={styles.container}>
      {/* Department Filter - SuperAdmin only */}
      {isSuperAdmin && (
        <div className={styles.departmentFilterRow}>
          <div className={styles.departmentFilterInner}>
            <span className={styles.departmentIcon}>
              <SVGIcons icon="folder" width={16} height={16} color="currentColor" />
            </span>
            <label className={styles.departmentLabel}>Department</label>
            <NewCommonDropdown
              options={departmentOptions}
              selected={selectedDepartment}
              onSelect={(value) => setSelectedDepartment(value)}
              placeholder="Select Department"
              showSearch={departmentOptions.length > 5}
              width="220px"
              maxWidth="280px"
              disabled={loadingDepartments}
            />
          </div>
          {selectedDepartment && (
            <span className={styles.departmentUserCount}>
              {filteredUsers.length} {filteredUsers.length === 1 ? "user" : "users"}
            </span>
          )}
        </div>
      )}

      {(loading || loadingDepartments) ? (
        <Loader />
      ) : filteredUsers.length === 0 ? (
        <EmptyState
          message={externalSearchTerm ? "No users match your search" : "No users found in this department"}
          icon="fa-user"
        />
      ) : (
        <div className={`display-cards-grid ${styles.cardGrid}`}>
          {filteredUsers.map((user) => (
            <div
              key={user.email}
              className={`${styles.userCard} ${!user.is_active ? styles.cardInactive : ""}`}
            >
              {/* Card Header */}
              <div className={styles.cardHeader}>
                <div className={styles.userInfo}>
                  <h4 className={styles.userName}>{user.user_name || "Unknown"}</h4>
                  <span className={styles.userEmail}>{user.email}</span>
                </div>
              </div>

              {/* Card Footer with Role on left and Toggles on right */}
              <div className={styles.cardFooter}>
                <span className={`${styles.roleTag} ${getRoleClass(user.role)}`}>
                  {user.role || "User"}
                </span>

                <div className={styles.togglesWrapper}>
                  {/* SuperAdmin: Show Global toggle */}
                  {isSuperAdmin && (
                    <div className={styles.toggleGroup}>
                      <span className={styles.toggleLabel}>Global</span>
                      <Toggle
                        value={user.global_is_active}
                        onChange={() => handleGlobalToggle(user)}
                      />
                    </div>
                  )}

                  {/* Both Admin & SuperAdmin: Show Active toggle */}
                  <div className={styles.toggleGroup}>
                    <span className={styles.toggleLabel}>Active</span>
                    <Toggle
                      value={user.is_active}
                      onChange={() => handleActiveToggle(user)}
                    />
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
});

export default UserManagement;
