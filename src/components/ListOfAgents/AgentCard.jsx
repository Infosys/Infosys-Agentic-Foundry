import React, { useEffect, useState } from "react";
import SVGIcons from "../../Icons/SVGIcons";
import Cookies from "js-cookie";
import DeleteModal from "../commonComponents/DeleteModal";
import { useAuth } from "../../context/AuthContext";
import { usePermissions } from "../../context/PermissionsContext";

// Helper function to get agent type abbreviation
const getAgentTypeAbbreviation = (agentType, typeOrDescription = "type") => {
  // Enhanced error handling for undefined/null/empty inputs
  if (!agentType || typeof agentType !== "string") {
    return typeOrDescription === "description" ? "Unknown Agent" : "UK";
  }

  // Map specific agent types to their abbreviations
  const abbreviationMap = {
    react_agent: { title: "RA", description: "React Agent" },
    react_critic_agent: { title: "RC", description: "React Critic" },
    planner_executor_agent: { title: "PE", description: "Planner Executor" },
    multi_agent: { title: "PC", description: "Planner Critic" },
    meta_agent: { title: "MA", description: "Meta Agent" },
    planner_meta_agent: { title: "MP", description: "Meta Planner" },
    hybrid_agent: { title: "HA", description: "Hybrid Agent" },
  };

  try {
    const mapping = abbreviationMap[agentType];

    // Return the mapped abbreviation or fallback to first two letters
    if (typeOrDescription === "description") {
      return mapping?.description || agentType || "Unknown Agent";
    }

    // Safer string manipulation with multiple fallbacks
    return mapping?.title || (agentType.length >= 2 ? agentType.substring(0, 2).toUpperCase() : agentType.toUpperCase()) || "UK";
  } catch (error) {
    console.warn("Error in getAgentTypeAbbreviation:", error, { agentType, typeOrDescription });
    return typeOrDescription === "description" ? "Unknown Agent" : "UK";
  }
};

const AgentCard = (props) => {
  const { styles, data, onAgentEdit, deleteAgent, fetchAgents, isSelected = false, onSelect, isUnusedSection = false, createdBy, lastUsed, createdOn } = props;

  const [isDeleteClicked, setIsDeleteClicked] = useState(false);
  const [email, setEmail] = useState("");
  const [deleteModal, setDeleteModal] = useState(false);

  const cardClassName = isUnusedSection ? styles["card-unused"] : props?.recycle ? styles.listContainerCss : styles.listContainer;

  const userName = Cookies.get("userName");
  const loggedInUserEmail = Cookies.get("email");
  const role = Cookies.get("role");

  useEffect(() => {
    userName === "Guest" ? setEmail(data.created_by) : setEmail(loggedInUserEmail);
  }, []);

  const { hasPermission, permissions } = usePermissions();

  const handleDelete = async (e) => {
    e.preventDefault();
    if (userName === "Guest") {
      setDeleteModal(true);
      return;
    }
    // Check delete permission for agents
    const canDelete =
      typeof hasPermission === "function" ? hasPermission("delete_access.agents") : !(permissions && permissions.delete_access && permissions.delete_access.agents === false);
    if (!canDelete) {
      setDeleteModal(true);
      return;
    }
    const isAdmin = role && role?.toUpperCase() === "ADMIN";
    try {
      const isDeleted = await deleteAgent(data?.agentic_application_id, email, isAdmin);
      fetchAgents();
      if (isDeleted) setIsDeleteClicked(false);
    } catch (error) {
      console.error(error);
    }
  };

  const closeModal = () => {
    setDeleteModal(false);
  };

  const { logout } = useAuth();

  const handleLoginButton = (e) => {
    e.preventDefault();
    logout("/login");
  };

  const cardDescription = data?.agentic_application_description;
  const cardDesc = cardDescription ? cardDescription.split(" ").slice(0, 5).join(" ") + (cardDescription.split(" ").length > 5 ? "..." : "") : "";

  return (
    <>
      <DeleteModal show={deleteModal} onClose={closeModal}>
        <p>You are not authorized to delete this agent. Please login with registered email.</p>
        <div className={styles.buttonContainer}>
          <button onClick={(e) => handleLoginButton(e)} className={styles.loginBtn}>
            Login
          </button>
          <button onClick={() => setDeleteModal(false)} className={styles.cancelBtn}>
            Cancel
          </button>
        </div>
      </DeleteModal>
      {!isDeleteClicked || props?.recycle ? (
        <div
          className={cardClassName}
          onClick={props?.recycle ? () => onAgentEdit(data) : undefined}
          style={{
            transition: "transform 0.2s ease, box-shadow 0.2s ease",
          }}
          onMouseOver={(e) => {
            e.currentTarget.style.transform = "translateY(-3px)";
            e.currentTarget.style.boxShadow = "5px 18px 10px #00000029";
          }}
          onMouseOut={(e) => {
            e.currentTarget.style.transform = "translateY(0)";
            e.currentTarget.style.boxShadow = "5px 15px 6px #00000029";
          }}>
          {isUnusedSection ? (
            <>
              <div className={styles.cardTitle}>{data?.agentic_application_name}</div>
            </>
          ) : props?.recycle ? (
            <>
              <div className={styles["card-title"]}>{props.data?.agentic_application_name}</div>
            </>
          ) : (
            <>
              <div className={styles.cardTitleRow}>
                <input
                  type="checkbox"
                  className={styles.agentCheckbox}
                  checked={isSelected}
                  onChange={(e) => onSelect && onSelect(data?.agentic_application_id, e.target.checked)}
                />
                <div className={styles["card-title"]}>{data?.agentic_application_name}</div>
              </div>
            </>
          )}

          <div className={styles.line} />
          {!isUnusedSection && (
            <>
              <div className={styles["card-description"]}></div>
              <div className={styles["card-description-title"]}>{cardDesc}</div>
            </>
          )}
          <div
            className={styles["agent-type-abbreviation"]}
            title={getAgentTypeAbbreviation(props?.recycle ? props.data?.agentic_application_type : data.agentic_application_type, "description")}>
            {getAgentTypeAbbreviation(props?.recycle ? props.data?.agentic_application_type : data.agentic_application_type, "title")}
          </div>
          {isUnusedSection && (
            <div className={styles["card-info"]}>
              <p className={styles["info-item"]}>
                <span className={styles["info-label"]}>Created by:</span>
                <span className={styles["info-value"]}>{createdBy}</span>
              </p>
              <p className={styles["info-item"]}>
                <span className={styles["info-label"]}>Created on:</span>
                <span className={styles["info-value"]}>{createdOn}</span>
              </p>
              <p className={styles["info-item"]}>
                <span className={styles["info-label"]}>Last used:</span>
                <span className={styles["info-value"]}>{lastUsed}</span>
              </p>
            </div>
          )}
          {!props?.recycle && (
            <div className={styles["btn-grp"]}>
              {(typeof hasPermission === "function"
                ? hasPermission("delete_access.agents")
                : !(permissions && permissions.delete_access && permissions.delete_access.agents === false)) && (
                <button className={styles.deleteBtn} onClick={() => setIsDeleteClicked(true)} title="Delete">
                  <SVGIcons icon="recycle-bin" width={20} height={20} />
                </button>
              )}
              {!isUnusedSection &&
                (typeof hasPermission === "function"
                  ? hasPermission("update_access.agents")
                  : !(permissions && permissions.update_access && permissions.update_access.agents === false)) && (
                  <button className={styles.editBtn} onClick={() => onAgentEdit(data)} title="Edit">
                    <SVGIcons icon="fa-solid fa-pen" width={20} height={20} />
                  </button>
                )}
            </div>
          )}
        </div>
      ) : (
        <form className={styles.listDeleteContainer} onSubmit={handleDelete}>
          <button className={styles["cancel-btn"]} onClick={() => setIsDeleteClicked(false)}>
            <SVGIcons icon="fa-xmark" fill="#3D4359" />
          </button>
          <input type="email" className={styles["email-id-input"]} value={data?.created_by} disabled />
          <div className={styles.actionInfo}>
            <span className={styles.warningIcon}>
              <SVGIcons icon="warnings" width={16} height={16} fill="#B8860B" />
            </span>
            creator / admin can perform this action
          </div>

          <button type="submit" className={styles.deleteBtnFull} onClick={handleDelete} title="Delete">
            DELETE
            <SVGIcons icon="recycle-bin" width={20} height={16} />
          </button>
        </form>
      )}
    </>
  );
};

export default AgentCard;
