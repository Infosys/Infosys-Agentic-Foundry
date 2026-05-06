import React, { useState, useEffect, useCallback } from "react";
import styles from "./NotificationPanel.module.css";
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import SVGIcons from "../../Icons/SVGIcons";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import { getDepartmentFromToken, getRoleFromToken } from "../../utils/jwtUtils";

/* ── Time formatting helpers ── */
const MS_PER_MINUTE = 60000;
const MS_PER_HOUR = 3600000;
const MS_PER_DAY = 86400000;
const MINUTES_PER_HOUR = 60;
const HOURS_PER_DAY = 24;
const DAYS_PER_WEEK = 7;

const formatDate = (dateStr) => {
  if (!dateStr) return "";
  const date = new Date(dateStr.replace(" ", "T"));
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / MS_PER_MINUTE);
  const diffHours = Math.floor(diffMs / MS_PER_HOUR);
  const diffDays = Math.floor(diffMs / MS_PER_DAY);

  if (diffMins < 1) return "Just now";
  if (diffMins < MINUTES_PER_HOUR) return `${diffMins}m ago`;
  if (diffHours < HOURS_PER_DAY) return `${diffHours}h ago`;
  if (diffDays < DAYS_PER_WEEK) return `${diffDays}d ago`;
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
};

const getStatusClass = (status) => {
  switch (status?.toLowerCase()) {
    case "pending":
      return styles.statusPending;
    case "approved":
      return styles.statusApproved;
    case "rejected":
      return styles.statusRejected;
    default:
      return styles.statusPending;
  }
};

const NotificationPanel = ({ onClose, requests = [], onRefresh, loading = false }) => {
  const { patchData, fetchData } = useFetch();
  const { handleApiError, handleApiSuccess } = useErrorHandler();

  // Logged-in user info
  const userRole = getRoleFromToken().toUpperCase();
  const userDepartment = getDepartmentFromToken();

  // Track which card is expanded for reject actions
  const [expandedId, setExpandedId] = useState(null);
  // Track which card is expanded for approve (role selection)
  const [approveExpandedId, setApproveExpandedId] = useState(null);
  // Selected role for approval
  const [selectedRole, setSelectedRole] = useState("");
  // Rejection reason per card
  const [rejectionReason, setRejectionReason] = useState("");
  // Loading state per request action
  const [actionLoading, setActionLoading] = useState(null);
  // Dynamic department roles for the approval dropdown
  const [departmentRoles, setDepartmentRoles] = useState([]);
  const [rolesLoading, setRolesLoading] = useState(false);

  // ── Multi-select state ──
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [bulkRole, setBulkRole] = useState("");
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkDepartmentRoles, setBulkDepartmentRoles] = useState([]);
  const [bulkRolesLoading, setBulkRolesLoading] = useState(false);
  const [bulkRejectionReason, setBulkRejectionReason] = useState("");
  const [showBulkRejectStrip, setShowBulkRejectStrip] = useState(false);
  const [showBulkApproveStrip, setShowBulkApproveStrip] = useState(false);

  /** Fetch roles for a given department */
  const fetchDepartmentRoles = useCallback(async (departmentName) => {
    if (!departmentName) {
      setDepartmentRoles([]);
      return;
    }
    setRolesLoading(true);
    try {
      const url = `${APIs.GET_DEPARTMENT_ROLES}${encodeURIComponent(departmentName)}/roles`;
      const response = await fetchData(url);
      const roles = Array.isArray(response) ? response
        : Array.isArray(response?.roles) ? response.roles
          : [];
      setDepartmentRoles(roles.map((r) => (typeof r === "string" ? r : r.role_name || r.name || String(r))));
    } catch {
      setDepartmentRoles([]);
    } finally {
      setRolesLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** When approve strip is expanded, fetch roles for the appropriate department */
  useEffect(() => {
    if (!approveExpandedId) {
      setDepartmentRoles([]);
      return;
    }
    const request = requests.find((r) => r.id === approveExpandedId);
    // SuperAdmin → use the request's department; Admin → use logged-in department
    const deptName = userRole === "SUPERADMIN" ? (request?.department_name || "") : userDepartment;
    fetchDepartmentRoles(deptName);
  }, [approveExpandedId, requests, userRole, userDepartment, fetchDepartmentRoles]);

  /** Approve a registration request with selected role */
  const handleApprove = async (requestId) => {
    if (!selectedRole) {
      handleApiError(new Error("Please select a role before approving."));
      return;
    }
    setActionLoading(requestId);
    try {
      const response = await patchData(APIs.APPROVE_REGISTRATION_REQUEST, {
        request_ids: [requestId],
        role: selectedRole,
      });
      handleApiSuccess(response);
      setApproveExpandedId(null);
      setSelectedRole("");
      if (onRefresh) onRefresh();
      // Notify other components (NavBar badge, UserManagement list) to refresh
      window.dispatchEvent(new CustomEvent("notificationAction", { detail: { action: "approved" } }));
    } catch {
      // Error handled by useFetch (handleApiError)
    } finally {
      setActionLoading(null);
    }
  };

  /** Reject a registration request with optional reason */
  const handleReject = async (requestId) => {
    setActionLoading(requestId);
    try {
      const response = await patchData(APIs.REJECT_REGISTRATION_REQUEST, {
        request_ids: [requestId],
        rejection_reason: rejectionReason || "",
      });
      handleApiSuccess(response);
      setExpandedId(null);
      setRejectionReason("");
      if (onRefresh) onRefresh();
      // Notify other components (NavBar badge) to refresh
      window.dispatchEvent(new CustomEvent("notificationAction", { detail: { action: "rejected" } }));
    } catch {
      // Error handled by useFetch (handleApiError)
    } finally {
      setActionLoading(null);
    }
  };

  /** Toggle the approve strip for a card */
  const toggleApproveStrip = (id) => {
    if (approveExpandedId === id) {
      setApproveExpandedId(null);
      setSelectedRole("");
    } else {
      setApproveExpandedId(id);
      setSelectedRole("");
      // Close reject strip if open
      setExpandedId(null);
      setRejectionReason("");
    }
  };

  /** Toggle the reject strip for a card */
  const toggleActions = (id) => {
    if (expandedId === id) {
      setExpandedId(null);
    } else {
      setExpandedId(id);
      setRejectionReason("");
      // Close approve strip if open
      setApproveExpandedId(null);
      setSelectedRole("");
    }
  };

  const pendingRequests = requests.filter(
    (r) => r.status?.toLowerCase() === "pending"
  );
  const pendingCount = pendingRequests.length;

  // ── Multi-select helpers ──
  const showMultiSelect = pendingCount > 1;

  const toggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const toggleSelectAll = () => {
    const pendingIds = pendingRequests.map((r) => r.id);
    const allSelected = pendingIds.every((id) => selectedIds.has(id));
    if (allSelected) {
      setSelectedIds(new Set());
      setBulkRole("");
    } else {
      setSelectedIds(new Set(pendingIds));
    }
  };

  const selectedCount = selectedIds.size;
  const allPendingSelected =
    pendingCount > 0 && pendingRequests.every((r) => selectedIds.has(r.id));

  /** Fetch roles for bulk approval based on selected requests */
  useEffect(() => {
    if (selectedCount === 0) {
      setBulkDepartmentRoles([]);
      setBulkRole("");
      return;
    }
    const selectedRequests = requests.filter((r) => selectedIds.has(r.id));
    // Use first selected request's department (or logged-in user's department for Admin)
    const deptName =
      userRole === "SUPERADMIN"
        ? selectedRequests[0]?.department_name || ""
        : userDepartment;
    if (!deptName) {
      setBulkDepartmentRoles([]);
      return;
    }
    const fetchBulkRoles = async () => {
      setBulkRolesLoading(true);
      try {
        const url = `${APIs.GET_DEPARTMENT_ROLES}${encodeURIComponent(deptName)}/roles`;
        const response = await fetchData(url);
        const roles = Array.isArray(response)
          ? response
          : Array.isArray(response?.roles)
            ? response.roles
            : [];
        setBulkDepartmentRoles(
          roles.map((r) =>
            typeof r === "string" ? r : r.role_name || r.name || String(r)
          )
        );
      } catch {
        setBulkDepartmentRoles([]);
      } finally {
        setBulkRolesLoading(false);
      }
    };
    fetchBulkRoles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCount]);

  /** Bulk approve all selected requests — single API call with request_ids list */
  const handleBulkApprove = async () => {
    if (!bulkRole) {
      handleApiError(new Error("Please select a role before approving."));
      return;
    }
    setBulkLoading(true);
    try {
      const response = await patchData(APIs.APPROVE_REGISTRATION_REQUEST, {
        request_ids: Array.from(selectedIds),
        role: bulkRole,
      });
      handleApiSuccess(response?.message ? response : { message: `${selectedCount} request(s) approved successfully.` });
      setSelectedIds(new Set());
      setBulkRole("");
      if (onRefresh) onRefresh();
      window.dispatchEvent(
        new CustomEvent("notificationAction", { detail: { action: "approved" } })
      );
    } catch {
      // Errors handled by useFetch
    } finally {
      setBulkLoading(false);
    }
  };

  /** Bulk reject all selected requests — single API call with request_ids list */
  const handleBulkReject = async () => {
    setBulkLoading(true);
    try {
      const response = await patchData(APIs.REJECT_REGISTRATION_REQUEST, {
        request_ids: Array.from(selectedIds),
        rejection_reason: bulkRejectionReason || "",
      });
      handleApiSuccess(response?.message ? response : { message: `${selectedCount} request(s) rejected successfully.` });
      setSelectedIds(new Set());
      setBulkRejectionReason("");
      setShowBulkRejectStrip(false);
      if (onRefresh) onRefresh();
      window.dispatchEvent(
        new CustomEvent("notificationAction", { detail: { action: "rejected" } })
      );
    } catch {
      // Errors handled by useFetch
    } finally {
      setBulkLoading(false);
    }
  };

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.panel} onClick={(e) => e.stopPropagation()}>
        {/* ── Header ── */}
        <div className={styles.header}>
          <div className={styles.headerTitle}>
            <SVGIcons icon="bell" width={18} height={18} />
            <span>Notifications</span>
            {pendingCount > 0 && (
              <span className={styles.headerBadge}>{pendingCount}</span>
            )}
          </div>
          <div className={styles.headerActions}>
            <button
              className={styles.closeBtn}
              onClick={onClose}
              title="Close"
              aria-label="Close notifications"
            >
              <SVGIcons icon="x" width={16} height={16} />
            </button>
          </div>
        </div>

        {/* ── Bulk Selection Bar ── */}
        {!loading && showMultiSelect && (
          <div className={styles.bulkBar}>
            <div className={styles.bulkBarTop}>
              <label className={styles.selectAllLabel}>
                <input
                  type="checkbox"
                  className={styles.checkbox}
                  checked={allPendingSelected}
                  onChange={toggleSelectAll}
                />
                <span>Select All ({pendingCount})</span>
              </label>
              {selectedCount > 0 && (
                <div className={styles.inlineActions}>
                  <button
                    className={`${styles.inlineApproveBtn} ${showBulkApproveStrip ? styles.inlineApproveBtnActive : ""}`}
                    onClick={() => {
                      setShowBulkApproveStrip((prev) => !prev);
                      setShowBulkRejectStrip(false);
                      setBulkRejectionReason("");
                    }}
                    disabled={bulkLoading}
                    title="Approve selected"
                    aria-label="Approve selected requests"
                  >
                    {bulkLoading && showBulkApproveStrip ? (
                      <span className={styles.btnSpinner} />
                    ) : (
                      <SVGIcons icon="check" width={14} height={14} />
                    )}
                  </button>
                  <button
                    className={`${styles.inlineRejectBtn} ${showBulkRejectStrip ? styles.inlineRejectBtnActive : ""}`}
                    onClick={() => {
                      setShowBulkRejectStrip((prev) => !prev);
                      setShowBulkApproveStrip(false);
                      setBulkRole("");
                    }}
                    disabled={bulkLoading}
                    title="Reject selected"
                    aria-label="Reject selected requests"
                  >
                    <SVGIcons icon="x" width={14} height={14} />
                  </button>
                </div>
              )}
            </div>

            {/* ── Bulk Approve Strip (role dropdown + confirm) ── */}
            {selectedCount > 0 && showBulkApproveStrip && (
              <div className={styles.approveStrip}>
                <div className={styles.roleDropdownWrapper}>
                  <NewCommonDropdown
                    options={bulkDepartmentRoles.filter(
                      (r) => userRole === "SUPERADMIN" || r.toLowerCase() !== "admin"
                    )}
                    selected={bulkRole}
                    onSelect={(option) => setBulkRole(option)}
                    placeholder={bulkRolesLoading ? "Loading..." : "Select role"}
                    showSearch={true}
                    width="100%"
                    disabled={bulkRolesLoading || bulkLoading}
                  />
                </div>
                <button
                  className={styles.approveConfirmBtn}
                  onClick={handleBulkApprove}
                  disabled={bulkLoading || !bulkRole}
                  title="Confirm approval"
                >
                  {bulkLoading && showBulkApproveStrip ? (
                    <span className={styles.btnSpinner} />
                  ) : (
                    "Approve"
                  )}
                </button>
                <button
                  className={styles.rejectCancelBtn}
                  onClick={() => { setShowBulkApproveStrip(false); setBulkRole(""); }}
                  disabled={bulkLoading}
                  title="Cancel"
                >
                  Cancel
                </button>
              </div>
            )}

            {/* ── Bulk Reject Strip (reason input + confirm) ── */}
            {selectedCount > 0 && showBulkRejectStrip && (
              <div className={styles.rejectStrip}>
                <input
                  type="text"
                  className={styles.reasonInput}
                  placeholder="Rejection reason (optional)..."
                  value={bulkRejectionReason}
                  onChange={(e) => setBulkRejectionReason(e.target.value)}
                  disabled={bulkLoading}
                  autoFocus
                />
                <button
                  className={styles.rejectConfirmBtn}
                  onClick={handleBulkReject}
                  disabled={bulkLoading}
                  title="Confirm rejection"
                >
                  {bulkLoading && showBulkRejectStrip ? (
                    <span className={styles.btnSpinner} />
                  ) : (
                    "Reject"
                  )}
                </button>
                <button
                  className={styles.rejectCancelBtn}
                  onClick={() => { setShowBulkRejectStrip(false); setBulkRejectionReason(""); }}
                  disabled={bulkLoading}
                  title="Cancel"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        )}

        {/* ── Content ── */}
        <div className={styles.content}>
          {loading && (
            <div className={styles.emptyState}>
              <div className={styles.spinner} />
              <p>Loading notifications...</p>
            </div>
          )}

          {!loading && requests.length === 0 && (
            <div className={styles.emptyState}>
              <SVGIcons icon="bell" width={40} height={40} />
              <p className={styles.emptyTitle}>No notifications</p>
              <p className={styles.emptySubtitle}>
                Registration requests will appear here
              </p>
            </div>
          )}

          {!loading && requests.length > 0 && (
            <div className={styles.requestList}>
              {requests.map((request) => {
                const isPending = request.status?.toLowerCase() === "pending";
                const isExpanded = expandedId === request.id;
                const isProcessing = actionLoading === request.id;

                return (
                  <div
                    key={request.id}
                    className={`${styles.requestCard} ${isExpanded ? styles.requestCardExpanded : ""
                      } ${selectedIds.has(request.id) ? styles.requestCardSelected : ""}`}
                  >
                    {/* ── Avatar + User Info ── */}
                    <div className={styles.requestTop}>
                      {showMultiSelect && isPending && (
                        <input
                          type="checkbox"
                          className={styles.checkbox}
                          checked={selectedIds.has(request.id)}
                          onChange={() => toggleSelect(request.id)}
                          aria-label={`Select ${request.user_name || "request"}`}
                        />
                      )}
                      <div className={styles.avatar}>
                        {(request.user_name || request.email_id || "?")
                          .charAt(0)
                          .toUpperCase()}
                      </div>
                      <div className={styles.requestInfo}>
                        <span className={styles.userName}>
                          {request.user_name || "Unknown User"}
                        </span>
                        <span className={styles.userEmail}>
                          {request.email_id || "—"}
                        </span>
                      </div>
                      <span
                        className={`${styles.statusBadge} ${getStatusClass(
                          request.status
                        )}`}
                      >
                        {request.status || "pending"}
                      </span>
                    </div>

                    {/* ── Meta info ── */}
                    <div className={styles.requestMeta}>
                      <div className={styles.metaItem}>
                        <span className={styles.metaLabel}>Department</span>
                        <span className={styles.metaValue}>
                          {request.department_name || "—"}
                        </span>
                      </div>
                      <div className={styles.metaItem}>
                        <span className={styles.metaLabel}>Requested</span>
                        <span className={styles.metaValue}>
                          {formatDate(request.created_at)}
                        </span>
                      </div>
                      {/* Inline action buttons for pending */}
                      {isPending && (
                        <div className={styles.inlineActions}>
                          <button
                            className={`${styles.inlineApproveBtn} ${approveExpandedId === request.id ? styles.inlineApproveBtnActive : ""
                              }`}
                            onClick={() => toggleApproveStrip(request.id)}
                            disabled={isProcessing}
                            title="Approve"
                            aria-label="Approve request"
                          >
                            {isProcessing && approveExpandedId === request.id ? (
                              <span className={styles.btnSpinner} />
                            ) : (
                              <SVGIcons icon="check" width={14} height={14} />
                            )}
                          </button>
                          <button
                            className={`${styles.inlineRejectBtn} ${isExpanded ? styles.inlineRejectBtnActive : ""
                              }`}
                            onClick={() => toggleActions(request.id)}
                            disabled={isProcessing}
                            title="Reject"
                            aria-label="Reject request"
                          >
                            <SVGIcons icon="x" width={14} height={14} />
                          </button>
                        </div>
                      )}
                    </div>

                    {/* ── Expanded Approve Strip with Role Dropdown ── */}
                    {isPending && approveExpandedId === request.id && (
                      <div className={styles.approveStrip}>
                        <div className={styles.roleDropdownWrapper}>
                          <NewCommonDropdown
                            options={departmentRoles.filter((r) => userRole === "SUPERADMIN" || r.toLowerCase() !== "admin")}
                            selected={selectedRole}
                            onSelect={(option) => setSelectedRole(option)}
                            placeholder={rolesLoading ? "Loading roles..." : "Select role"}
                            showSearch={true}
                            width="100%"
                            disabled={rolesLoading}
                          />
                        </div>
                        <button
                          className={styles.approveConfirmBtn}
                          onClick={() => handleApprove(request.id)}
                          disabled={isProcessing || !selectedRole}
                          title="Confirm approval"
                        >
                          {isProcessing ? (
                            <span className={styles.btnSpinner} />
                          ) : (
                            "Approve"
                          )}
                        </button>
                        <button
                          className={styles.rejectCancelBtn}
                          onClick={() => toggleApproveStrip(request.id)}
                          disabled={isProcessing}
                          title="Cancel"
                        >
                          Cancel
                        </button>
                      </div>
                    )}

                    {/* ── Expanded Reject Strip ── */}
                    {isPending && isExpanded && (
                      <div className={styles.rejectStrip}>
                        <input
                          id={`reason-${request.id}`}
                          type="text"
                          className={styles.reasonInput}
                          placeholder="Reason (optional)..."
                          value={rejectionReason}
                          onChange={(e) => setRejectionReason(e.target.value)}
                          disabled={isProcessing}
                          autoFocus
                        />
                        <button
                          className={styles.rejectConfirmBtn}
                          onClick={() => handleReject(request.id)}
                          disabled={isProcessing}
                          title="Confirm rejection"
                        >
                          {isProcessing ? (
                            <span className={styles.btnSpinner} />
                          ) : (
                            "Reject"
                          )}
                        </button>
                        <button
                          className={styles.rejectCancelBtn}
                          onClick={() => toggleActions(request.id)}
                          disabled={isProcessing}
                          title="Cancel"
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default NotificationPanel;
