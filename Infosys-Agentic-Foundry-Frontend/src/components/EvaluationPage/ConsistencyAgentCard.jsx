import React, { useState } from "react";
import { getRoleFromToken } from "../../utils/jwtUtils";
import styles from "../../css_modules/AvailableAgents.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { APIs } from "../../constant";
import useAxios from "../../Hooks/useAxios";
import { useMessage } from "../../Hooks/MessageContext";

const ConsistencyAgentCard = ({ agent, onDelete, onEdit, onScore, isLoading, isLast, lastCardRef }) => {
  const [isDeleteConfirm, setIsDeleteConfirm] = useState(false);
  const [loading, setLoading] = useState(false);
  const { addMessage } = useMessage();
  const { deleteData } = useAxios(); // useAxios returns an object with fetchData, not the function itself

  // Show confirmation UI when delete icon is clicked
  const handleShowDeleteConfirm = (e) => {
    e.preventDefault();
    setIsDeleteConfirm(true);
  };

  // Cancel delete confirmation
  const handleCancelDelete = (e) => {
    e.preventDefault();
    setIsDeleteConfirm(false);
  };

  // Actual delete API call
  const handleConfirmDelete = async (e) => {
    e.preventDefault();
    // Use agent_id for delete, since agentic_application_id is not present in response
    const agenticId = agent?.agentic_application_id || agent?.agent_id;
    if (!agenticId) {
      addMessage("Agent ID is required for delete.", "error");
      setIsDeleteConfirm(false);
      return;
    }
    setLoading(true);
    try {
      const isAdmin = getRoleFromToken().toLowerCase() === "admin";
      const payload = { agentic_application_ids: [agenticId], is_admin: isAdmin };
      const response = await deleteData(APIs.CONSISTENCY_DELETE_AGENT, payload);
      if (response && typeof response !== "string") {
        const statusMsg = response.status_message || response.message;
        if (statusMsg) {
          const hasAnyFailure = Array.isArray(response.results) && response.results.some((r) => r.is_delete === false);
          addMessage(statusMsg, hasAnyFailure ? "error" : "success");
        }
      }
      setIsDeleteConfirm(false);
      if (typeof onDelete === "function") {
        await onDelete(agent);
      }
    } catch (error) {
      const errorMsg = error?.response?.data?.detail || error?.response?.data?.message || error?.message;
      if (errorMsg) addMessage(errorMsg, "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.listContainer} ref={isLast ? lastCardRef : null} style={{ position: "relative" }}>
      {!isDeleteConfirm ? (
        <>
          <div className={styles.cardTitleRow}>
            <div className={styles["card-title"]}>{agent.agentic_application_name || agent.agent_name || "Unnamed Agent"}</div>
            <span style={{ marginLeft: "8px" }}>
              <SVGIcons icon="fa-solid fa-circle-check" width={16} height={16} style={{ color: "#43a047" }} />
            </span>
          </div>
          <div className={styles.line} />
          <div className={styles["card-description-title"]}>{agent.agentic_application_name || agent.agent_name || "Unnamed Agent"}</div>
          <div className={styles["btn-grp"]}>
            <button
              className={styles.consistencyCardBtn}
              type="button"
              style={{
                background: "#007ac0",
                borderRadius: "3px",
                width: "28px",
                height: "24px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                border: "none",
              }}
              title="View details"
              aria-label={`View ${agent.agentic_application_name || agent.agent_name || "agent"}`}
              onClick={onScore ? () => onScore(agent) : null}
              disabled={isLoading || loading}>
              <SVGIcons icon="eye" width={20} height={16} fill="#fff" />
            </button>
            <button className={`${styles.deleteBtn} ${styles.consistencyCardBtn}`} onClick={handleShowDeleteConfirm} title="Delete" disabled={isLoading || loading}>
              <SVGIcons icon="recycle-bin" width={20} height={16} />
            </button>
            <button className={`${styles.editBtn} ${styles.consistencyCardBtn}`} onClick={() => onEdit(agent)} title="Edit" disabled={isLoading || loading}>
              <SVGIcons icon="fa-solid fa-pen" width={16} height={16} />
            </button>
          </div>
        </>
      ) : (
        <form
          className={styles.listDeleteContainer}
          onSubmit={handleConfirmDelete}
          style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", zIndex: 2, display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <button className={styles["cancel-btn"]} type="button" onClick={handleCancelDelete} disabled={isLoading || loading} style={{ alignSelf: "flex-end" }}>
            <SVGIcons icon="fa-xmark" fill="#3D4359" />
          </button>
          <button
            type="submit"
            className={styles.deleteBtnFull}
            title="Delete"
            disabled={isLoading || loading || !(agent?.agentic_application_id || agent?.agent_id)}
            style={{ marginTop: "10px" }}>
            DELETE
            <SVGIcons icon="recycle-bin" width={20} height={16} />
          </button>
          {!(agent?.agentic_application_id || agent?.agent_id) && (
            <div style={{ color: "red", fontWeight: "bold", marginBottom: "8px" }}>Agent ID missing! Cannot delete this agent.</div>
          )}
        </form>
      )}
    </div>
  );
};

export default ConsistencyAgentCard;
