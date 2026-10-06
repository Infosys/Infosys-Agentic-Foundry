import React, { useState, useEffect, useCallback, useImperativeHandle, forwardRef } from "react";
import { APIs, roleOptions } from "../../constant";
import { getDepartmentFromToken, getRoleFromToken, getEmailFromToken } from "../../utils/jwtUtils";
import useFetch from "../../Hooks/useAxios";
import { useMessage } from "../../Hooks/MessageContext";
import Toggle from "../commonComponents/Toggle";
import Loader from "../commonComponents/Loader";
import EmptyState from "../commonComponents/EmptyState";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import SVGIcons from "../../Icons/SVGIcons";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";
import styles from "./UserManagement.module.css";
import "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1.css";

const normalizeEmail = (value) => (value || "").trim().toLowerCase();

const parseDeptEntry = (entry) => {
  try {
    return typeof entry === "string" ? JSON.parse(entry) : entry;
  } catch {
    return null;
  }
};

const isSuperAdminRoleName = (role) =>
  (role || "").toLowerCase().replace(/[\s_-]/g, "") === "superadmin";

const userHasSuperAdminAccess = (user, superAdminEmailSet) => {
  const email = normalizeEmail(user.email);
  if (email && superAdminEmailSet?.has(email)) return true;

  const deptEntries = (user.departments || []).map(parseDeptEntry).filter(Boolean);
  if (deptEntries.some((entry) => isSuperAdminRoleName(entry.role))) return true;

  return isSuperAdminRoleName(user.role);
};

const getApiErrorMessage = (err, fallback) =>
  err?.response?.data?.detail ||
  err?.response?.data?.message ||
  err?.message ||
  fallback;

/** One card per department membership — original card layout preserved. */
const buildUserCards = (user, { isSuperAdminUser, selectedDepartment, isSuperAdmin }) => {
  const deptEntries = (user.departments || []).map(parseDeptEntry).filter(Boolean);
  const cardRole = user.role || deptEntries[0]?.role || "User";
  const email = user.email;
  const filterDept =
    isSuperAdmin && selectedDepartment && selectedDepartment !== "All" ? selectedDepartment : null;

  const entries = filterDept
    ? deptEntries.filter((d) => (d.department_name || "Global") === filterDept)
    : deptEntries;

  if (entries.length === 0) {
    if (filterDept) return [];
    return [
      {
        ...user,
        user_name: user.username || user.user_name || "",
        department_name: "Global",
        role: cardRole,
        is_active: user.status === "Active",
        _isSuperAdminUser: isSuperAdminUser,
        _cardKey: `${email}_Global`,
      },
    ];
  }

  return entries.map((d) => ({
    ...user,
    user_name: user.username || user.user_name || "",
    department_name: d.department_name || "Global",
    role: d.role || cardRole,
    is_active: d.is_active ?? user.status === "Active",
    _isSuperAdminUser: isSuperAdminUser,
    _cardKey: `${email}_${d.department_name || "Global"}`,
  }));
};

/**
 * UserManagement Component
 * 
 * Card-based layout matching Tools/Servers/Agents pages.
 * Admin: Active toggle for the logged-in department
 * SuperAdmin: Department/role filters, active toggle for non-SuperAdmin roles, promote/revoke icons
 * 
 * Exposes renderDepartmentDropdown via ref for parent to render next to search
 */
const UserManagement = forwardRef(({ externalSearchTerm = "", onReady, includeSuperAdminRoleFilter = false }, ref) => {
  const loggedInDepartment = getDepartmentFromToken();
  const userRole = getRoleFromToken();
  const normalizedRole = (userRole || "").toLowerCase().replace(/[\s_-]/g, "");
  const isSuperAdmin = normalizedRole === "superadmin";
  const canManageSuperAdminAccess = includeSuperAdminRoleFilter && isSuperAdmin;
  const currentUserEmail = normalizeEmail(getEmailFromToken());

  const PAGE_SIZE = 12;

  // State
  const [users, setUsers] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [selectedDepartment, setSelectedDepartment] = useState(isSuperAdmin ? "All" : loggedInDepartment);
  const [selectedRole, setSelectedRole] = useState("All");
  const [loading, setLoading] = useState(false);
  const [loadingDepartments, setLoadingDepartments] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [superAdminEmails, setSuperAdminEmails] = useState(() => new Set());
  const [showPromoteConfirm, setShowPromoteConfirm] = useState(false);
  const [showRevokeSuperAdminConfirm, setShowRevokeSuperAdminConfirm] = useState(false);
  const [selectedSuperAdminUser, setSelectedSuperAdminUser] = useState(null);
  const [superAdminSubmitting, setSuperAdminSubmitting] = useState(false);

  const { fetchData, patchData, postData } = useFetch();
  const { addMessage } = useMessage();

  /**
   * Fetch departments list from /departments/list (SuperAdmin only)
   */
  const fetchDepartments = useCallback(async () => {
    if (!isSuperAdmin) return;

    setLoadingDepartments(true);
    try {
      const response = await fetchData(APIs.GET_DEPARTMENTS_LIST);
      if (Array.isArray(response)) {
        setDepartments(response);
      } else if (response?.departments && Array.isArray(response.departments)) {
        setDepartments(response.departments);
      }
    } catch (error) {
      console.error("Failed to fetch departments:", error);
    } finally {
      setLoadingDepartments(false);
    }
  }, [isSuperAdmin, fetchData]);

  const fetchSuperAdminEmails = useCallback(async () => {
    if (!canManageSuperAdminAccess) return;

    try {
      const params = [
        "page_number=1",
        "page_size=100",
        `role=${encodeURIComponent("SuperAdmin")}`,
      ];
      const endpoint = `${APIs.GET_DEPARTMENT_USERS_SEARCH_PAGINATED}?${params.join("&")}`;
      const response = await fetchData(endpoint);
      const users = Array.isArray(response?.users) ? response.users : [];
      const emails = users
        .map((user) => normalizeEmail(user.email || user.mail_id))
        .filter(Boolean);
      setSuperAdminEmails(new Set(emails));
    } catch (error) {
      console.error("Failed to fetch Super Admin list:", error);
      setSuperAdminEmails(new Set());
    }
  }, [canManageSuperAdminAccess, fetchData]);

  /**
   * Fetch users using search-paginated endpoint
   */
  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const params = [];
      params.push(`page_number=${currentPage}`);
      params.push(`page_size=${PAGE_SIZE}`);

      if (isSuperAdmin && selectedDepartment && selectedDepartment !== "All") {
        params.push(`department=${encodeURIComponent(selectedDepartment)}`);
      }

      if (externalSearchTerm && externalSearchTerm.trim()) {
        params.push(`search_value=${encodeURIComponent(externalSearchTerm.trim())}`);
      }

      if (selectedRole && selectedRole !== "All") {
        params.push(`role=${encodeURIComponent(selectedRole)}`);
      }

      const endpoint = `${APIs.GET_DEPARTMENT_USERS_SEARCH_PAGINATED}?${params.join("&")}`;
      const response = await fetchData(endpoint);

      if (response?.users && Array.isArray(response.users)) {
        const parsed = response.users.flatMap((user) => {
          const isSuperAdminUser = userHasSuperAdminAccess(user, superAdminEmails);
          return buildUserCards(user, {
            isSuperAdminUser,
            selectedDepartment,
            isSuperAdmin,
          });
        });
        setUsers(parsed);
        setTotalCount(response.total || response.count || parsed.length);
      } else {
        setUsers([]);
        setTotalCount(0);
      }
    } catch (error) {
      addMessage("Failed to fetch users", "error");
      setUsers([]);
      setTotalCount(0);
    } finally {
      setLoading(false);
    }
  }, [selectedDepartment, currentPage, externalSearchTerm, selectedRole, fetchData, addMessage, isSuperAdmin, superAdminEmails]);

  useEffect(() => {
    if (canManageSuperAdminAccess) {
      fetchSuperAdminEmails();
    }
  }, [canManageSuperAdminAccess, fetchSuperAdminEmails]);

  // Fetch departments on mount for SuperAdmin
  useEffect(() => {
    if (isSuperAdmin) {
      fetchDepartments();
    }
  }, [isSuperAdmin, fetchDepartments]);

  // Reset page when search, department, or role changes
  useEffect(() => {
    setCurrentPage(1);
  }, [externalSearchTerm, selectedDepartment, selectedRole]);

  // Fetch users when dependencies change
  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  // Refresh user list when a registration request is approved
  useEffect(() => {
    const handleNotificationAction = (e) => {
      if (e.detail?.action === "approved") {
        fetchUsers();
      }
    };
    window.addEventListener("notificationAction", handleNotificationAction);
    return () => window.removeEventListener("notificationAction", handleNotificationAction);
  }, [fetchUsers]);

  /**
   * Handle Active toggle (department-level)
   * Sends: { email_id, is_active, global_is_active, department_name }
   */
  const handleActiveToggle = async (user) => {
    const newValue = !user.is_active;
    const cardKey = user._cardKey;

    setUsers((prevUsers) =>
      prevUsers.map((u) => (u._cardKey === cardKey ? { ...u, is_active: newValue } : u))
    );

    try {
      await patchData(APIs.SET_USER_ACTIVE_STATUS, {
        email_id: user.email,
        is_active: newValue,
        global_is_active: user.global_is_active,
        department_name: user.department_name || selectedDepartment || null,
      });
      addMessage(`User ${newValue ? "activated" : "deactivated"} in ${user.department_name}`, "success");
    } catch (error) {
      setUsers((prevUsers) =>
        prevUsers.map((u) => (u._cardKey === cardKey ? { ...u, is_active: !newValue } : u))
      );
      const errorMessage = error?.response?.data?.detail || error?.message || "Failed to update user status";
      addMessage(errorMessage, "error");
    }
  };

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

  const isSuperAdminRole = (role) => isSuperAdminRoleName(role);

  const onlyOneSuperAdmin = superAdminEmails.size <= 1;

  const openPromoteSuperAdminConfirm = (user) => {
    setSelectedSuperAdminUser(user);
    setShowPromoteConfirm(true);
  };

  const openRevokeSuperAdminConfirm = (user) => {
    setSelectedSuperAdminUser(user);
    setShowRevokeSuperAdminConfirm(true);
  };

  const handlePromoteSuperAdmin = async () => {
    if (!selectedSuperAdminUser?.email) return;

    setSuperAdminSubmitting(true);
    try {
      const response = await postData(APIs.PROMOTE_SUPERADMIN, {
        target_email: selectedSuperAdminUser.email,
      });
      addMessage(
        response?.message ||
        `${selectedSuperAdminUser.email} promoted to Super Admin`,
        "success"
      );
      setShowPromoteConfirm(false);
      setSelectedSuperAdminUser(null);
      await Promise.all([fetchSuperAdminEmails(), fetchUsers()]);
    } catch (error) {
      addMessage(getApiErrorMessage(error, "Failed to promote user to Super Admin"), "error");
    } finally {
      setSuperAdminSubmitting(false);
    }
  };

  const handleRevokeSuperAdmin = async () => {
    if (!selectedSuperAdminUser?.email) return;

    setSuperAdminSubmitting(true);
    try {
      const response = await postData(APIs.REVOKE_SUPERADMIN, {
        target_email: selectedSuperAdminUser.email,
      });
      addMessage(
        response?.message ||
        `SuperAdmin access revoked for ${selectedSuperAdminUser.email}.`,
        "success"
      );
      setShowRevokeSuperAdminConfirm(false);
      setSelectedSuperAdminUser(null);
      await Promise.all([fetchSuperAdminEmails(), fetchUsers()]);
    } catch (error) {
      addMessage(getApiErrorMessage(error, "Failed to revoke Super Admin access"), "error");
    } finally {
      setSuperAdminSubmitting(false);
    }
  };

  const promoteConfirmMessage = selectedSuperAdminUser
    ? `Are you sure you want to promote ${selectedSuperAdminUser.email} to Super Admin? This user will gain full system access.`
    : "";

  const revokeSuperAdminConfirmMessage = selectedSuperAdminUser
    ? `Revoke SuperAdmin access for ${selectedSuperAdminUser.email}? This cannot be undone.`
    : "";

  /**
   * Get department name helper
   */
  const getDepartmentName = (dept) => {
    if (typeof dept === "string") return dept;
    return dept?.department_name || dept?.name || "";
  };

  /**
   * Transform departments to dropdown options format - include "All" for SuperAdmin
   */
  const departmentOptions = isSuperAdmin
    ? ["All", ...departments.map(dept => getDepartmentName(dept))]
    : departments.map(dept => getDepartmentName(dept));

  /**
   * Role filter options - hardcoded from constant, include "All" at the top.
   * Super Admin page only: include SuperAdmin so it can be filtered via the same users endpoint.
   */
  const roleFilterOptions = includeSuperAdminRoleFilter
    ? ["All", ...roleOptions, "SuperAdmin"]
    : ["All", ...roleOptions];

  /**
   * Pagination helpers
   */
  const totalPages = Math.ceil(totalCount / PAGE_SIZE);

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
            <label className={styles.departmentLabel}>Department</label>
            <NewCommonDropdown
              options={departmentOptions}
              selected={selectedDepartment}
              onSelect={(value) => setSelectedDepartment(value)}
              placeholder="Select Department"
              showSearch={false}
              width="220px"
              maxWidth="280px"
              disabled={loadingDepartments}
            />
          </div>
          <div className={styles.departmentFilterInner}>
            <label className={styles.departmentLabel}>Role</label>
            <NewCommonDropdown
              options={roleFilterOptions}
              selected={selectedRole}
              onSelect={(value) => setSelectedRole(value)}
              placeholder="Select Role"
              showSearch={false}
              width="180px"
              maxWidth="220px"
            />
          </div>
          {selectedDepartment && (
            <span className={styles.departmentUserCount}>
              {totalCount} {totalCount === 1 ? "user" : "users"}
            </span>
          )}
        </div>
      )}

      {(loading || loadingDepartments) ? (
        <Loader />
      ) : users.length === 0 ? (
        <EmptyState
          message={externalSearchTerm ? "No users match your search" : "No users found in this department"}
          icon="fa-user"
        />
      ) : (
        <>
          <div className={`display-cards-grid ${styles.cardGrid}`}>
            {users.map((user) => (
              <div
                key={user._cardKey || user.email}
                className={`${styles.userCard} ${!user.is_active ? styles.cardInactive : ""}`}
              >
                {/* Card Header */}
                <div className={styles.cardHeader}>
                  <div className={styles.userInfo}>
                    <h4 className={styles.userName}>{user.user_name || user.username || "Unknown"}</h4>
                    <span className={styles.userEmail}>{user.email}</span>
                  </div>
                </div>

                {/* Card Footer with Role, Department, toggle, and actions */}
                <div className={styles.cardFooter}>
                  <div className={styles.badgesWrapper}>
                    <span className={`${styles.roleTag} ${getRoleClass(user.role)}`}>
                      {user.role || "User"}
                    </span>
                    {user.department_name && (
                      <span className={styles.departmentTag}>
                        {user.department_name}
                      </span>
                    )}
                  </div>

                  <div className={styles.cardFooterActions}>
                    {!isSuperAdminRole(user.role) && (
                      <div className={styles.togglesWrapper}>
                        <div className={styles.toggleGroup}>
                          <span className={styles.toggleLabel}>Active</span>
                          <Toggle
                            value={user.is_active}
                            onChange={() => handleActiveToggle(user)}
                          />
                        </div>
                      </div>
                    )}

                    {canManageSuperAdminAccess && (
                      <div className={styles.cardActions}>
                        {user._isSuperAdminUser ? (
                          <button
                            type="button"
                            className={`${styles.cardActionBtn} ${styles.cardRevokeIconBtn}`}
                            onClick={() => openRevokeSuperAdminConfirm(user)}
                            disabled={
                              superAdminSubmitting ||
                              normalizeEmail(user.email) === currentUserEmail ||
                              onlyOneSuperAdmin
                            }
                            aria-label="Revoke Super Admin access"
                            title={
                              normalizeEmail(user.email) === currentUserEmail
                                ? "You cannot revoke your own access"
                                : onlyOneSuperAdmin
                                  ? "Cannot revoke the only remaining SuperAdmin"
                                  : "Revoke Super Admin access"
                            }
                          >
                            <SVGIcons icon="fa-solid fa-user-xmark" width={16} height={16} color="currentColor" />
                          </button>
                        ) : (
                          <button
                            type="button"
                            className={`${styles.cardActionBtn} ${styles.cardPromoteIconBtn}`}
                            onClick={() => openPromoteSuperAdminConfirm(user)}
                            disabled={
                              superAdminSubmitting ||
                              normalizeEmail(user.email) === currentUserEmail
                            }
                            aria-label="Promote to Super Admin"
                            title={
                              normalizeEmail(user.email) === currentUserEmail
                                ? "You cannot promote yourself"
                                : "Promote to Super Admin"
                            }
                          >
                            <SVGIcons icon="fa-user-plus" width={16} height={16} color="currentColor" />
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Pagination Controls */}
          {totalCount > PAGE_SIZE && (
            <div className={styles.paginationControls}>
              <div className={styles.paginationInfo}>
                Showing {Math.min((currentPage - 1) * PAGE_SIZE + 1, totalCount)} to{" "}
                {Math.min(currentPage * PAGE_SIZE, totalCount)} of {totalCount}
              </div>
              <div className={styles.paginationButtons}>
                <button
                  onClick={() => setCurrentPage((p) => p - 1)}
                  disabled={currentPage === 1}
                  className={styles.paginationButton}
                >
                  Previous
                </button>
                {(() => {
                  const pages = [];
                  const maxVisible = 5;
                  const halfVisible = Math.floor(maxVisible / 2);
                  let startPage = Math.max(1, currentPage - halfVisible);
                  const endPage = Math.min(totalPages, startPage + maxVisible - 1);
                  if (endPage - startPage < maxVisible - 1) {
                    startPage = Math.max(1, endPage - maxVisible + 1);
                  }
                  for (let i = startPage; i <= endPage; i++) {
                    pages.push(
                      <button
                        key={i}
                        onClick={() => setCurrentPage(i)}
                        className={`${styles.paginationButton} ${i === currentPage ? styles.paginationActive : ""}`}
                      >
                        {i}
                      </button>
                    );
                  }
                  return pages;
                })()}
                <button
                  onClick={() => setCurrentPage((p) => p + 1)}
                  disabled={currentPage === totalPages}
                  className={styles.paginationButton}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {showPromoteConfirm && selectedSuperAdminUser && (
        <ConfirmationModal
          message={promoteConfirmMessage}
          onConfirm={handlePromoteSuperAdmin}
          setShowConfirmation={setShowPromoteConfirm}
          loading={superAdminSubmitting}
          confirmLabel="Promote to Super Admin"
        />
      )}

      {showRevokeSuperAdminConfirm && selectedSuperAdminUser && (
        <ConfirmationModal
          message={revokeSuperAdminConfirmMessage}
          onConfirm={handleRevokeSuperAdmin}
          setShowConfirmation={(value) => {
            setShowRevokeSuperAdminConfirm(value);
            if (!value) setSelectedSuperAdminUser(null);
          }}
          loading={superAdminSubmitting}
          confirmLabel="Revoke Access"
        />
      )}
    </div>
  );
});

export default UserManagement;