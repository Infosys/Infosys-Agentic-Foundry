import React, { useEffect, useState } from "react";
import SVGIcons from "../../Icons/SVGIcons";
import Cookies from "js-cookie";
import DeleteModal from "../commonComponents/DeleteModal";
import { useAuth } from "../../context/AuthContext";

// Helper function to get agent type abbreviation
const getAgentTypeAbbreviation = (agentType) => {
  if (!agentType) return "";

  // Map specific agent types to their abbreviations
  const abbreviationMap = {
    react_agent: "RA",
    react_critic_agent: "RC",
    planner_executor_agent: "PE",
    multi_agent: "PC",
    meta_agent: "MA",
    planner_meta_agent: "MP",
  };

  // Return the mapped abbreviation or fallback to first two letters
  return abbreviationMap[agentType] || agentType.substring(0, 2).toUpperCase();
};

const AgentCard = (props) => {
  const { styles, data, onAgentEdit, deleteAgent, fetchAgents, isSelected = false, onSelect } = props;

  const [isDeleteClicked, setIsDeleteClicked] = useState(false);
  const [email, setEmail] = useState("");
  const [deleteModal, setDeleteModal] = useState(false);

  const userName = Cookies.get("userName");
  const loggedInUserEmail = Cookies.get("email");
  const role = Cookies.get("role");

  useEffect(() => {
    userName === "Guest" ? setEmail(data.created_by) : setEmail(loggedInUserEmail);
  }, []);

  const handleDelete = async (e) => {
    e.preventDefault();
    if (userName === "Guest") {
      setDeleteModal(true);
      return;
    }
    const isAdmin = role && role.toUpperCase() === "ADMIN";
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
          className={props?.recycle ? styles.listContainerCss : styles.listContainer}
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
          {props?.recycle ? (
            <>
              <div className={styles["card-title"]}>{props?.recycle ? props.data?.agentic_application_name : data?.agentic_application_name}</div>
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
          <div className={styles["card-description"]}></div>
          <div className={styles["card-description-title"]}>{cardDesc}</div>
          <div className={styles["agent-type-abbreviation"]}>{getAgentTypeAbbreviation(props?.recycle ? props.data?.agentic_application_type : data.agentic_application_type)}</div>
          {!props?.recycle && (
            <div className={styles["btn-grp"]}>
              <>
                <button className={styles.deleteBtn} onClick={() => setIsDeleteClicked(true)}>
                  <SVGIcons icon="fa-solid fa-user-xmark" width={20} height={16} />
                </button>
                <button className={styles.editBtn} onClick={() => onAgentEdit(data)}>
                  <SVGIcons icon="fa-solid fa-pen" width={16} height={16} />
                </button>
              </>
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

          <button type="submit" className={styles.deleteBtnFull} onClick={handleDelete}>
            DELETE
            <SVGIcons icon="fa-solid fa-user-xmark" width={15} height={12} />
          </button>
        </form>
      )}
    </>
  );
};

export default AgentCard;
