import React, { useState, useEffect, useCallback, useRef } from "react";
import ReactDOM from "react-dom";
import styles from "./ShareModal.module.css";
import SVGIcons from "../../../Icons/SVGIcons";
import Toggle from "../Toggle";
import DepartmentSelector from "../DepartmentSelector/DepartmentSelector";
import IAFButton from "../../../iafComponents/GlobalComponents/Buttons/Button";
import useFetch from "../../../Hooks/useAxios";
import { APIs } from "../../../constant";
import { useMessage } from "../../../Hooks/MessageContext";
import { getDepartmentFromToken } from "../../../utils/jwtUtils";

/**
 * ShareModal - A popup for managing department sharing on any entity.
 *
 * @param {Object} props
 * @param {boolean} props.show - Whether to show the modal
 * @param {Function} props.onClose - Callback to close the modal
 * @param {Object} props.itemData - The entity data (tool/agent/server/kb)
 * @param {string} props.entityType - "tool" | "agent" | "server" | "knowledge base"
 */
function ShareModal({ show, onClose, itemData, entityType = "tool" }) {
  const [isPublic, setIsPublic] = useState(false);
  const [sharedDepartments, setSharedDepartments] = useState([]);
  const [departmentsList, setDepartmentsList] = useState([]);
  const [departmentsLoading, setDepartmentsLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const { fetchData, putData } = useFetch();
  const { addMessage } = useMessage();
  const previousDataRef = useRef({ isPublic: false, sharedDepartments: [] });

  const loggedInDepartment = getDepartmentFromToken();

  // Derive entity ID & name based on entityType
  const getEntityInfo = useCallback(() => {
    if (!itemData) return { id: null, name: "Unknown" };

    switch (entityType) {
      case "tool":
        return { id: itemData.tool_id || itemData.id, name: itemData.tool_name || itemData.name };
      case "agent":
        return { id: itemData.agentic_application_id || itemData.agent_id || itemData.id, name: itemData.agentic_application_name || itemData.agent_name || itemData.name };
      case "server":
        return { id: itemData.tool_id || itemData.server_id || itemData.id, name: itemData.tool_name || itemData.name || itemData.server_name };
      case "knowledge base":
        return { id: itemData.kb_id || itemData.id, name: itemData.name || itemData.kb_name };
      case "workflow":
        return { id: itemData.workflow_id || itemData.id, name: itemData.workflow_name || itemData.name };
      default:
        return { id: itemData.id, name: itemData.name };
    }
  }, [itemData, entityType]);

  // Build GET sharing endpoint
  const getSharingUrl = useCallback(() => {
    const { id } = getEntityInfo();
    if (!id) return null;

    switch (entityType) {
      case "tool":
        return `${APIs.GET_TOOL_SHARING}${encodeURIComponent(id)}/sharing-info`;
      case "agent":
        return `${APIs.GET_AGENT_SHARING}${encodeURIComponent(id)}/sharing-info`;
      case "server":
        return `${APIs.GET_SERVER_SHARING}${encodeURIComponent(id)}/sharing-info`;
      case "knowledge base":
        return `${APIs.GET_KB_SHARING}${encodeURIComponent(id)}/sharing-info`;
      case "workflow":
        return `${APIs.GET_WORKFLOW_SHARING}${encodeURIComponent(id)}/sharing-info`;
      default:
        return null;
    }
  }, [entityType, getEntityInfo]);

  // Build PUT sharing endpoint
  const getUpdateSharingUrl = useCallback(() => {
    const { id } = getEntityInfo();
    if (!id) return null;

    switch (entityType) {
      case "tool":
        return `${APIs.UPDATE_TOOL_SHARING}${encodeURIComponent(id)}/sharing`;
      case "agent":
        return `${APIs.UPDATE_AGENT_SHARING}${encodeURIComponent(id)}/sharing`;
      case "server":
        return `${APIs.UPDATE_SERVER_SHARING}${encodeURIComponent(id)}/sharing`;
      case "knowledge base":
        return `${APIs.UPDATE_KB_SHARING}${encodeURIComponent(id)}/sharing`;
      case "workflow":
        return `${APIs.UPDATE_WORKFLOW_SHARING}${encodeURIComponent(id)}/sharing`;
      default:
        return null;
    }
  }, [entityType, getEntityInfo]);

  // Fetch departments list
  const fetchDepartmentsList = useCallback(async () => {
    setDepartmentsLoading(true);
    try {
      const response = await fetchData(APIs.GET_DEPARTMENTS_LIST);
      if (response) {
        const list = Array.isArray(response) ? response : (response.data || response.departments || []);
        const deptNames = list.map((d) => (typeof d === "string" ? d : d.name || d.department_name));
        setDepartmentsList(deptNames);
      }
    } catch {
      // Silent fail - departmentsList will be empty
    } finally {
      setDepartmentsLoading(false);
    }
  }, [fetchData]);

  // Fetch current sharing info
  const fetchSharingInfo = useCallback(async () => {
    const url = getSharingUrl();
    if (!url) return;

    setLoading(true);
    setError("");
    try {
      const response = await fetchData(url);
      if (response) {
        const publicVal = response.is_public ?? false;
        const depts = response.shared_with ?? [];

        setIsPublic(publicVal);
        setSharedDepartments(depts);
        previousDataRef.current = { isPublic: publicVal, sharedDepartments: depts };
      }
    } catch {
      setError("Failed to load sharing info. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [fetchData, getSharingUrl]);

  // Load data when modal opens
  useEffect(() => {
    if (show && itemData) {
      fetchSharingInfo();
      fetchDepartmentsList();
    }
  }, [show, itemData, fetchSharingInfo, fetchDepartmentsList]);

  // Save sharing updates
  const handleSave = async () => {
    const url = getUpdateSharingUrl();
    if (!url) return;

    // Check if anything changed
    const prev = previousDataRef.current;
    if (
      prev.isPublic === isPublic &&
      JSON.stringify(prev.sharedDepartments.sort()) === JSON.stringify(sharedDepartments.sort())
    ) {
      onClose();
      return;
    }

    setSaving(true);
    setError("");
    try {
      const payload = {
        is_public: isPublic,
        shared_with_departments: isPublic ? [] : sharedDepartments,
      };

      await putData(url, payload);
      addMessage("Sharing settings updated successfully", "success");
      onClose();
    } catch {
      setError("Failed to update sharing settings. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  // Close on Escape key
  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === "Escape" && show) {
        onClose();
      }
    };
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [show, onClose]);

  if (!show) return null;

  const { name } = getEntityInfo();
  const entityLabel = entityType.charAt(0).toUpperCase() + entityType.slice(1);

  return ReactDOM.createPortal(
    <div
      className={styles.overlay}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={`Share ${entityLabel}`}
    >
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerLeft}>
            <div className={styles.headerIcon}>
              <SVGIcons icon="share" width={18} height={18} color="#10b981" />
            </div>
            <div>
              <h3 className={styles.headerTitle}>Share {entityLabel}</h3>
              <p className={styles.headerSubtitle} title={name}>{name}</p>
            </div>
          </div>
          <button className={styles.closeBtn} onClick={onClose} aria-label="Close">
            <SVGIcons icon="x" width={18} height={18} />
          </button>
        </div>

        {/* Body */}
        <div className={styles.body}>
          {loading ? (
            <div className={styles.loadingContainer}>
              <div className={styles.spinner} />
              <span className={styles.loadingText}>Loading sharing settings...</span>
            </div>
          ) : (
            <>
              {error && (
                <div className={styles.errorContainer}>
                  <SVGIcons icon="warnings" width={16} height={16} color="#dc2626" />
                  <span className={styles.errorText}>{error}</span>
                </div>
              )}

              {/* Visible to All Departments Toggle */}
              <div className={styles.toggleRow}>
                <div>
                  <div className={styles.toggleLabel}>Visible to All Departments</div>
                  <div className={styles.toggleDescription}>
                    {isPublic ? "Everyone can access this " + entityType : "Only shared departments can access"}
                  </div>
                </div>
                <Toggle value={isPublic} onChange={() => setIsPublic((prev) => !prev)} />
              </div>

              {/* Department Selector (shown when NOT public) */}
              {!isPublic && (
                <div className={styles.departmentSection}>
                  <div className={styles.sectionLabel}>Share with Departments</div>
                  <DepartmentSelector
                    selectedDepartments={sharedDepartments}
                    onChange={setSharedDepartments}
                    departmentsList={departmentsList.filter((d) => d !== loggedInDepartment)}
                    loading={departmentsLoading}
                    placeholder="Select departments to share with..."
                  />
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        {!loading && (
          <div className={styles.footer}>
            <IAFButton type="secondary" onClick={onClose} disabled={saving}>
              Cancel
            </IAFButton>
            <IAFButton type="primary" onClick={handleSave} disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </IAFButton>
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}

export default ShareModal;
