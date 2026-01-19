import React, { useState, useEffect, useMemo } from "react";
import SVGIcons from "../../Icons/SVGIcons";
import { useToolsAgentsService } from "../../services/toolService";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faBan } from "@fortawesome/free-solid-svg-icons";
import { useMessage } from "../../Hooks/MessageContext";
import { usePermissions } from "../../context/PermissionsContext";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import Cookies from "js-cookie";
import DeleteModal from "../commonComponents/DeleteModal";
import { useAuth } from "../../context/AuthContext";
import styles from "../../css_modules/AvailableTools.module.css";

function ToolsCard(props) {
  const { setIsAddTool, setShowForm, setEditTool, loading, tool = {}, fetchPaginatedTools, isUnusedSection = false, createdBy, lastUsed } = props;

  // Normalize tool data based on section
  const normalizedTool = useMemo(() => {
    if (!tool) return {};

    // For unused section, prefer 'name', otherwise prefer 'tool_name'
    const displayName = isUnusedSection ? tool.name || tool.tool_name || "Unnamed Tool" : tool.tool_name || tool.name || "Unnamed Tool";

    return {
      id: tool.id || tool.tool_id,
      name: displayName,
      description: tool.description || tool.tool_description,
      created_by: createdBy,
      created_on: tool.created_on,
    };
  }, [tool, isUnusedSection]);
 

  // Validate required props
  useEffect(() => {
    if (!tool || typeof tool !== "object") {
      console.error("Invalid tool data provided to ToolsCard:", tool);
    }
  }, [tool, isUnusedSection, normalizedTool]);

  const [isDeleteClicked, setIsDeleteClicked] = useState(false);
  const [emailId, setEmailId] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const { deleteTool } = useToolsAgentsService();

  const { addMessage, setShowPopup } = useMessage();

  const [deleteModal, setDeleteModal] = useState(false);

  const loggedInUserEmail = Cookies.get("email");
  const userName = Cookies.get("userName");
  const role = Cookies.get("role");

  useEffect(() => {
    userName === "Guest" ? setEmailId(tool.created_by) : setEmailId(loggedInUserEmail);
  }, [userName, tool.created_by, loggedInUserEmail]);

  useEffect(() => {
    if (!loading) {
      setShowPopup(true);
    } else {
      setShowPopup(false);
    }
  }, [loading, setShowPopup]);

  const { handleApiError, handleApiSuccess } = useErrorHandler();

  const { permissions, hasPermission } = usePermissions();

  const canUpdate = typeof hasPermission === "function" ? hasPermission("update_access.tools") : !(permissions && permissions.update_access && permissions.update_access.tools === false);
  const canDelete = typeof hasPermission === "function" ? hasPermission("delete_access.tools") : !(permissions && permissions.delete_access && permissions.delete_access.tools === false);

  const handelDeleteTools = async (toolId) => {
    if (!toolId) {
      addMessage("Cannot delete tool: ID is missing", "error");
      return;
    }

    if (userName === "Guest") {
      setDeleteModal(true);
      return;
    }

    const isAdmin = role && role?.toUpperCase() === "ADMIN";
    const data = {
      user_email_id: emailId,
      is_admin: isAdmin,
    };
    try {
      const response = await deleteTool(data, toolId);
      if (response?.is_delete) {
        if (typeof fetchPaginatedTools === "function") {
          await fetchPaginatedTools(1);
        }
        setIsDeleteClicked(false);
        setEmailId("");
        // Prefer backend detail; fallback defined in handler
        handleApiSuccess(response, { fallbackMessage: "Tool deleted" });
      } else {
        // Non-success shape returned (maybe error object from service) – surface detail via error handler
        handleApiError(response);
        setErrorMessage("Unauthorized");
      }
    } catch (e) {
      handleApiError(e);
      setErrorMessage("Unauthorized");
    }
  };

  // handleChange removed - email input is disabled in delete flow and email is managed elsewhere

  const { logout } = useAuth();

  const handleLoginButton = (e) => {
    e.preventDefault();
    logout("/login");
  };

  const handleEditClick = async () => {
    setShowForm(true);
    setIsAddTool(false);
    setEditTool(tool);
  };

  return (
    <>
      <DeleteModal show={deleteModal} onClose={() => setDeleteModal(false)}>
        <p>You are not authorized to delete this tool. Please login with registered email.</p>
        <div className={styles.buttonContainer}>
          <button onClick={(e) => handleLoginButton(e)} className={styles.loginBtn}>
            Login
          </button>
          <button onClick={() => setDeleteModal(false)} className={styles.cancelBtn}>
            Cancel
          </button>
        </div>
      </DeleteModal>
      <div
        key={normalizedTool.id}
        className={`${isDeleteClicked ? styles["delete-card"] : ""} ${props?.recycle ? styles["cardRecycle"] : ""} ${isUnusedSection ? styles["card-unused"] : styles["card"]}`}
        onClick={props?.recycle ? handleEditClick : () => {}}>
        {!isDeleteClicked && (
          <>
            <div>
              <p className={styles["card-title"]}>{normalizedTool.name || "Unnamed Tool"}</p>
              <div className={styles["dash"]}></div>
              {!isUnusedSection && (
                <>
                  <p className={styles["card-description"]}></p>
                  <p className={styles["card-description-title"]}>{normalizedTool.description}</p>
                </>
              )}
              <div
                style={{
                  position: "absolute",
                  left: "2px",
                  bottom: "10px",
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  pointerEvents: "none", // ensure underlying buttons remain clickable
                }}>
                {(() => {
                  const isValidatorFlag = (() => {
                    if (tool.tool_id  && String(tool.tool_id).toLowerCase().startsWith("_validator")) return true;
                    return false;
                  })();

                  return (
                    <span
                      className={styles.typePill}
                      style={{
                        fontSize: "12px",
                        padding: "4px 10px",
                        background: "#6b7280",
                        color: "#fff",
                        borderRadius: "8px",
                        textTransform: "uppercase",
                        letterSpacing: "0.5px",
                      }}
                      title={isValidatorFlag ? "Validator tool" : "Standard tool"}>
                      {isValidatorFlag ? "VALIDATOR" : "TOOL"}
                    </span>
                  );
                })()}
              </div>
              {isUnusedSection && (
                <div className={styles["card-info"]}>
                  <div className={styles["info-item"]}>
                    <div className={styles["info-label"]}>Created by:</div>
                    <div className={styles["info-value"]}>{createdBy}</div>
                  </div>
                  <div className={styles["info-item"]}>
                    <div className={styles["info-label"]}>Created on:</div>
                    <div className={styles["info-value"]}>{tool.created_on || "-"}</div>
                  </div>
                  <div className={styles["info-item"]}>
                    <div className={styles["info-label"]}>Last used:</div>
                    <div className={styles["info-value"]}>{lastUsed}</div>
                  </div>
                </div>
              )}
              {!props?.recycle && (
                <div className={styles["btn-grp"]}>
                  {canDelete && (
                    <button
                      onClick={() => {
                        setErrorMessage(false);
                        setIsDeleteClicked(true);
                      }}
                      title={"Delete"}
                      className={styles["deleteBtn"]}>
                      <SVGIcons icon="recycle-bin" width={20} height={16} />
                    </button>
                  )}
                  {!isUnusedSection && canUpdate && (
                    <button
                      onClick={handleEditClick}
                      className={styles["editBtn"]}
                      title={"Edit"}>
                      <SVGIcons icon="fa-solid fa-pen" width={16} height={16} />
                    </button>
                  )}
                </div>
              )}
            </div>
          </>
        )}

        {isDeleteClicked && (
          <>
            <button className={styles["cancel-btn"]} onClick={() => setIsDeleteClicked(false)}>
              <SVGIcons icon="fa-xmark" fill="#3D4359" />
            </button>
            <input className={styles["email-id-input"]} type="text" value={createdBy} disabled></input>
            <div className={styles["action-info"]}>
              <span className={styles.warningIcon}>
                <SVGIcons icon="warnings" width={16} height={16} fill="#B8860B" />
              </span>
              creator / admin can perform this action
            </div>
            {errorMessage && (
              <p className={styles["error"]}>
                <FontAwesomeIcon icon={faBan} />
                &nbsp;
                {errorMessage}
              </p>
            )}
            <div className={styles["delete-btn-container"]}>
              <button
                onClick={() => {
                  const toolId = tool?.id || tool?.tool_id;
                  if (!toolId) {
                    addMessage("Cannot delete tool: ID is missing", "error");
                    return;
                  }
                  handelDeleteTools(toolId);
                }}>
                DELETE <SVGIcons icon="fa-circle-xmark" width={16} height={16} />
              </button>
            </div>
          </>
        )}
      </div>
    </>
  );
}

export default ToolsCard;
