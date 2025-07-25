  import React, { useState, useEffect } from "react";
  import SVGIcons from "../../Icons/SVGIcons";
  import { deleteTool } from "../../services/toolService";
  import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
  import { faBan } from "@fortawesome/free-solid-svg-icons";
  import { useMessage } from "../../Hooks/MessageContext";
  import Cookies from "js-cookie";
  import DeleteModal from "../commonComponents/DeleteModal";
  import { useNavigate } from "react-router-dom";

  function ToolsCard(props) {
    const {
      setIsAddTool,
      setShowForm,
      setEditTool,
      style,
      loading,
      tool,
      fetchPaginatedTools
    } = props;
    const [isDeleteClicked, setIsDeleteClicked] = useState(false);
    const [emailId, setEmailId] = useState("");
    const [errorMessage, setErrorMessage] = useState("");

    const { addMessage, setShowPopup } = useMessage();

    const [deleteModal, setDeleteModal] = useState(false);

    const loggedInUserEmail = Cookies.get("email");
    const userName = Cookies.get("userName");
    const role = Cookies.get("role");

    useEffect(() => {
      userName === "Guest"
        ? setEmailId(tool.created_by)
        : setEmailId(loggedInUserEmail);
    }, []);

    useEffect(() => {
      if (!loading) {
        setShowPopup(true);
      } else {
        setShowPopup(false);
      }
    }, [loading]);

    const handelDeleteTools = async (toolId) => {
      if (userName === "Guest") {
        setDeleteModal(true);
        return;
      }
      const isAdmin = role && role.toUpperCase() === "ADMIN";
      const data = {
        user_email_id: emailId,
        is_admin: isAdmin,
      };
      const response = await deleteTool(data, toolId);
      if (response?.is_delete) {
        if (typeof fetchPaginatedTools === "function") {
          await fetchPaginatedTools(1);
        }
        setIsDeleteClicked(false);
        setEmailId("");
        addMessage("Tool has been deleted successfully!", "success");
      } else {
        addMessage((response?.status_message) ? response?.status_message : "No response received. Please try again.", "error");
        setErrorMessage("Unauthorized");
      }
    };

    const handleChange = (e) => {
      setEmailId(e?.target?.value);
      setErrorMessage("");
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

    const handleEditClick = async () => {      
      setShowForm(true);
      setIsAddTool(false);
      setEditTool(tool);
    };

    return (
      <>
        <DeleteModal show={deleteModal} onClose={() => setDeleteModal(false)}>
          <p>
            You are not authorized to delete this tool. Please login with
            registered email.
          </p>
          <button onClick={(e) => handleLoginButton(e)}>Login</button>
        </DeleteModal>
        <div
          key={tool.tool_id}
          className={
  isDeleteClicked
    ? style["card"] + " " + style["delete-card"]
    : props?.recycle
    ? style["cardRecycle"]
    : style["card"]
}
        >
          {!isDeleteClicked && (
            <>
            <div onClick={props?.recycle ?handleEditClick:undefined}>
              <p className={style["card-title"]}>{tool.tool_name}</p>
              <div className={style["dash"]}></div>
              <p className={style["card-description"]}></p>
              <p className={style["card-description-title"]}>
                {tool.tool_description}
              </p>
              {!props?.recycle &&(
                <div className={style["btn-grp"]}>
                <button
                  onClick={() => {
                    setErrorMessage(false);
                    setIsDeleteClicked(true);
                  }}
                  className={style["deleteBtn"]}
                >
                  <SVGIcons
                    icon="fa-solid fa-user-xmark"
                    width={20}
                    height={16}
                  />
                </button>
                <button onClick={handleEditClick} className={style["editBtn"]}>
                  <SVGIcons icon="fa-solid fa-pen" width={16} height={16} />
                </button>
              </div>
              )}
              
            </div>
            </>
          )}

          {isDeleteClicked && (
            <>
              <button
                className={style["cancel-btn"]}
                onClick={() => setIsDeleteClicked(false)}
              >
                <SVGIcons icon="fa-xmark" fill="#3D4359" />
              </button>
              <input
                className={style["email-id-input"]}
                type="text"
                value={tool?.created_by}
                disabled
              ></input>
              <div className={style["action-info"]}>
                <span className={style.warningIcon}>
                            <SVGIcons icon="warnings" width={16} height={16} fill="#B8860B"/>
                          </span>
                creator / admin can perform this action
              </div>
              {errorMessage && (
                <p className={style["error"]}>
                  <FontAwesomeIcon icon={faBan} />
                  &nbsp;
                  {errorMessage}
                </p>
              )}
              <div className={style["delete-btn-container"]}>
                <button onClick={() => handelDeleteTools(tool.tool_id)}>
                  DELETE <SVGIcons icon="fa-circle-xmark" />
                </button>
              </div>
            </>
          )}
        </div>
      </>
    );
  }

  export default ToolsCard;
