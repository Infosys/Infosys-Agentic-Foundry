import React, { useState, useEffect, useCallback, useMemo } from "react";
import { createPortal } from "react-dom";
import styles from "./Requests.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import CheckBox from "../../iafComponents/GlobalComponents/CheckBox/CheckBox";
import TextField from "../../iafComponents/GlobalComponents/TextField/TextField";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import { useRequestsService } from "../../services/requestsService";
import { getDepartmentFromToken } from "../../utils/jwtUtils";

/**
 * RaiseRequestModal — Centered modal for requesting department access.
 * Follows the app's ExportFilesModal / WarningModal pattern:
 *   - Uses global CSS vars (--modal-overlay, --backdrop-blur, --radius-lg, etc.)
 *   - Uses global keyframes (iafFadeIn, iafModalEnter)
 *   - Uses design-system components (IAFButton, CheckBox, TextField)
 */
const RaiseRequestModal = ({ onClose, onSuccess, existingRequests = [] }) => {
  const [departments, setDepartments] = useState([]);
  const [selectedDepartments, setSelectedDepartments] = useState([]);
  const [loadingDepts, setLoadingDepts] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [deptSearch, setDeptSearch] = useState("");
  const { handleApiError, handleApiSuccess } = useErrorHandler();
  const { getDepartmentsList, requestDepartmentAccess } = useRequestsService();

  // Map department name → existing request status
  const existingStatusMap = useMemo(() => {
    const map = {};
    existingRequests.forEach((r) => {
      const name = (r.department_name || "").toLowerCase();
      if (name) map[name] = (r.status || "pending").toLowerCase();
    });
    return map;
  }, [existingRequests]);

  // ──── Fetch departments ────
  const fetchDepartments = useCallback(async () => {
    setLoadingDepts(true);
    try {
      const response = await getDepartmentsList();
      const list =
        response?.departments ?? response?.data?.departments ?? (Array.isArray(response) ? response : []);
      setDepartments(list);
    } catch {
      // Error handled by useFetch (handleApiError)
      setDepartments([]);
    } finally {
      setLoadingDepts(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    fetchDepartments();
  }, [fetchDepartments]);

  // ──── Handlers ────
  const toggleDepartment = (name) => {
    setSelectedDepartments((prev) =>
      prev.includes(name) ? prev.filter((d) => d !== name) : [...prev, name]
    );
  };

  const handleSubmit = async () => {
    if (selectedDepartments.length === 0) {
      handleApiError(new Error("Please select at least one department."));
      return;
    }
    setSubmitting(true);
    try {
      const response = await requestDepartmentAccess(selectedDepartments);
      if (response?.error || response?.detail || response?.approval === false) {
        handleApiError(response);
      } else {
        handleApiSuccess(response);
        onSuccess?.();
      }
    } catch {
      // Error handled by useFetch (handleApiError)
    } finally {
      setSubmitting(false);
    }
  };

  // Close on Escape
  useEffect(() => {
    const handleKey = (e) => {
      if (e.key === "Escape" && !submitting) onClose?.();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose, submitting]);

  // Lock body scroll
  useEffect(() => {
    const original = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = original;
    };
  }, []);

  // Normalize departments & exclude the user's current department
  const currentDepartment = getDepartmentFromToken().toLowerCase();

  const normalizedDepts = useMemo(
    () =>
      departments
        .map((dept) => {
          const name = typeof dept === "string" ? dept : dept.department_name || dept.name || "";
          return { name };
        })
        .filter((d) => d.name.toLowerCase() !== currentDepartment),
    [departments, currentDepartment]
  );

  // Filter by search
  const filteredDepts = useMemo(
    () =>
      deptSearch
        ? normalizedDepts.filter((d) => d.name.toLowerCase().includes(deptSearch.toLowerCase()))
        : normalizedDepts,
    [normalizedDepts, deptSearch]
  );

  // ──── Skeleton loading ────
  // eslint-disable-next-line no-magic-numbers
  const SKELETON_ITEMS = [0, 1, 2, 3, 4];
  const renderSkeleton = () =>
    SKELETON_ITEMS.map((i) => (
      <div key={i} className={styles.deptItemSkeleton}>
        <div className={`${styles.skeletonLine} ${styles.skeletonMedium}`} />
      </div>
    ));

  // Status label renderer
  const renderStatusLabel = (status) => {
    const cls = [
      styles.deptStatusLabel,
      status === "approved" ? styles.deptStatusApproved : "",
      status === "pending" ? styles.deptStatusPending : "",
      status === "rejected" ? styles.deptStatusRejected : "",
    ]
      .filter(Boolean)
      .join(" ");

    return (
      <span className={cls}>
        <span className={styles.deptStatusDot} />
        {status}
      </span>
    );
  };

  const modalContent = (
    <div
      className={styles.modalOverlay}
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose?.();
      }}
    >
      <div
        className={`${styles.modalContainer} ${submitting ? styles.submitting : ""}`}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="raise-request-title"
      >
        {/* ── Header ── */}
        <div className={styles.modalHeader}>
          <div className={styles.modalHeaderLeft}>
            <h3 id="raise-request-title" className={styles.modalTitle}>
              Request Department Access
            </h3>
          </div>
          <button
            className={styles.modalCloseBtn}
            onClick={onClose}
            disabled={submitting}
            aria-label="Close modal"
          >
            <SVGIcons icon="x" width={20} height={20} />
          </button>
        </div>

        {/* ── Body ── */}
        <div className={styles.modalBody}>
          {/* Search */}
          <TextField
            placeholder="Search departments..."
            value={deptSearch}
            onChange={(e) => setDeptSearch(e.target.value)}
            showClearButton={true}
            showSearchButton={true}
            onClear={() => setDeptSearch("")}
          />

          {/* Department list */}
          <div className={styles.deptList}>
            {loadingDepts ? (
              renderSkeleton()
            ) : filteredDepts.length === 0 ? (
              <div className={styles.deptEmptyMsg}>
                <SVGIcons icon="search" width={20} height={20} />
                <span>
                  {deptSearch ? "No departments match your search" : "No departments available"}
                </span>
              </div>
            ) : (
              filteredDepts.map(({ name }) => {
                const existingStatus = existingStatusMap[name.toLowerCase()];
                const isDisabled = existingStatus === "approved" || existingStatus === "pending";
                const isSelected = selectedDepartments.includes(name);

                return (
                  <div
                    key={name}
                    className={[
                      styles.deptItem,
                      isSelected ? styles.deptItemSelected : "",
                      isDisabled ? styles.deptItemDisabled : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    onClick={() => !isDisabled && toggleDepartment(name)}
                    title={
                      isDisabled
                        ? `Already ${existingStatus}`
                        : isSelected
                          ? `Deselect ${name}`
                          : `Select ${name}`
                    }
                  >
                    <CheckBox
                      checked={isSelected}
                      onChange={() => toggleDepartment(name)}
                      disabled={isDisabled}
                      label={name}
                    />
                    <span className={styles.deptItemName}>{name}</span>
                    {existingStatus && renderStatusLabel(existingStatus)}
                  </div>
                );
              })
            )}
          </div>

          {/* Selected chips */}
          {selectedDepartments.length > 0 && (
            <div className={styles.selectedChips}>
              {selectedDepartments.map((dept) => (
                <span key={dept} className={styles.chip}>
                  {dept}
                  <button
                    className={styles.chipRemove}
                    onClick={() => toggleDepartment(dept)}
                    aria-label={`Remove ${dept}`}
                  >
                    <SVGIcons icon="x" width={10} height={10} />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {/* ── Footer ── */}
        <div className={styles.modalFooter}>
          <div className={styles.footerActions}>
            <IAFButton type="secondary" onClick={onClose} disabled={submitting}>
              Cancel
            </IAFButton>
            <IAFButton
              type="primary"
              onClick={handleSubmit}
              disabled={submitting || selectedDepartments.length === 0}
              loading={submitting}
            >
              {submitting ? "Submitting..." : "Submit Request"}
            </IAFButton>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
};

export default RaiseRequestModal;
