import React, { useEffect, useState } from "react";
import SVGIcons from "../../Icons/SVGIcons";
import Cookies from "js-cookie";
import DeleteModal from "../commonComponents/DeleteModal";
import { useNavigate } from "react-router-dom";

const AgentCard = (props) => {
  const { styles, data, onAgentEdit, deleteAgent, fetchAgents } = props;

  const [isDeleteClicked, setIsDeleteClicked] = useState(false);
  const [email, setEmail] = useState("");
  const [deleteModal, setDeleteModal] = useState(false);

  const userName = Cookies.get("userName");
  const loggedInUserEmail = Cookies.get("email");

  useEffect(() => {
    userName === "Guest"
      ? setEmail(data.created_by)
      : setEmail(loggedInUserEmail);
  }, []);

  const handleDelete = async (e) => {
    e.preventDefault();

    if (userName === "Guest") {
      setDeleteModal(true);
      return;
    }

    try {
      const isDeleted = await deleteAgent(data?.agentic_application_id, email);
      fetchAgents();
      if (isDeleted) setIsDeleteClicked(false);
    } catch (error) {
      console.error(error);
    }
  };

  const closeModal = () => {
    setDeleteModal(false);
  };

  const navigate = useNavigate();

  const handleLoginButton = (e) => {
    e.preventDefault();
    Cookies.remove("userName");
    Cookies.remove("session_id");
    Cookies.remove("csrf-token");
    Cookies.remove("email");
    Cookies.remove("role");
    navigate("/login");
  };

  const cardDescription = data?.agentic_application_description;
  const cardDesc = cardDescription
  ? cardDescription
      .split(" ")
      .slice(0, 5)
      .join(" ") + (cardDescription.split(" ").length > 5 ? "..." : "")
  : "";

  return (
    <>
      <DeleteModal show={deleteModal} onClose={closeModal}>
        <p>
          You are not authorized to delete this agent. Please login with
          registered email.
        </p>
        <button onClick={(e) => handleLoginButton(e)}>Login</button>
      </DeleteModal>
      {!isDeleteClicked ? (
        <div className={styles.listContainer}>
          <div className={styles["card-title"]}>{data.agentic_application_name}</div>
          <div className={styles.line} />
          <div className={styles["card-description"]}></div>
          <div className={styles["card-description-title"]}>{cardDesc}</div>
          <button
            className={styles.deleteBtn}
            onClick={() => setIsDeleteClicked(true)}
          >
            <SVGIcons icon="fa-solid fa-user-xmark" width={20} height={16} />
          </button>
          <button className={styles.editBtn} onClick={() => onAgentEdit(data)}>
            <SVGIcons icon="fa-solid fa-pen" width={16} height={16} />
          </button>
        </div>
      ) : (
        <form className={styles.listDeleteContainer} onSubmit={handleDelete}>
          <input
            type="email"
            placeholder="ENTER EMAIL"
            className={styles.deleteInput}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />

          <button
            type="submit"
            className={styles.deleteBtnFull}
            onClick={handleDelete}
          >
            DELETE
            <SVGIcons icon="fa-solid fa-user-xmark" width={15} height={12} />
          </button>
        </form>
      )}
    </>
  );
};

export default AgentCard;
