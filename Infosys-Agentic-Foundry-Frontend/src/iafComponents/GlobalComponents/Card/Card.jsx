import React, { useState, useEffect } from "react";
import CheckBox from "../CheckBox/CheckBox";
import Header from "../Header/Header";
import Description from "../Description";
import Category from "../Type";
import SVGIcons from "../../../Icons/SVGIcons";
import DeleteModal from "../../../components/commonComponents/DeleteModal";
import Cookies from "js-cookie";
import { card_config } from "../../../constant";
import "./Card.css";

// Helper function for agent type abbreviations (reusable for any type)
const getTypeAbbreviation = (type, mode = "title", customMappings = {}) => {
  if (!type || typeof type !== "string") {
    return mode === "description" ? "Unknown Type" : "UK";
  }

  // Default agent type mappings (can be extended)
  const defaultMappings = {
    react_agent: { title: "RA", description: "React Agent" },
    react_critic_agent: { title: "RC", description: "React Critic" },
    planner_executor_agent: { title: "PE", description: "Planner Executor" },
    multi_agent: { title: "PC", description: "Planner Critic" },
    meta_agent: { title: "MA", description: "Meta Agent" },
    planner_meta_agent: { title: "MP", description: "Meta Planner" },
    hybrid_agent: { title: "HA", description: "Hybrid Agent" },
    // Add more mappings as needed
    ...customMappings,
  };

  try {
    const mapping = defaultMappings[type.toLowerCase()];

    if (mode === "description") {
      return mapping?.description || type || "Unknown Type";
    }

    return mapping?.title || (type.length >= 2 ? type.substring(0, 2).toUpperCase() : type.toUpperCase()) || "UK";
  } catch (error) {
    console.warn("Error in getTypeAbbreviation:", error, { type, mode });
    return mode === "description" ? "Unknown Type" : "UK";
  }
};

const Card = ({
  cardName,
  cardDescription,
  cardOwner,
  cardCategory,
  cardDepartment = "", // NEW: department name for department badge
  showcheckbox = false,
  onSelectionChange,
  isSelected = false,
  showbutton = false,
  onButtonClick,
  buttonText = "⋯",
  showChatButton = false,
  onChatClick,
  showDeleteButton = false,
  onDeleteClick, // Callback signature: onDeleteClick(cardName, cardData) - receives both name and full data object
  skipDeleteConfirmation = false, // NEW: skip internal confirmation, call onDeleteClick directly
  onCardClick,
  // Enhanced props for reusability
  showEditButton = false,
  onEditClick,
  isUnusedSection = false,
  cardCreatedBy,
  cardCreatedOn,
  cardLastUsed,
  cardData = {},
  loading = false,
  isRecycleMode = false,
  // Props for complex delete functionality
  enableComplexDelete = false,
  onComplexDelete,
  deleteModalContent,
  onLoginRequired,
  // New props for agent functionality and general reusability
  showTypeAbbreviation = false,
  cardType = "",
  typeMappings = {},
  enableHoverEffects = false,
  hoverTransform = "translateY(-3px)",
  hoverShadow = "5px 18px 10px #00000029",
  normalShadow = "5px 15px 6px #00000029",
  customLayout = "default", // "default", "agent", "tool", "compact"
  truncateDescription = 0, // 0 = no truncation, number = word limit
  checkboxPosition = "left", // "left", "right", "top"
  isListView = false, // Indicates if the card is in list view mode
  showDescription = true, // NEW: controls rendering of description
  onInfoClick, // NEW: callback for info button click
  buttonIcon, // NEW: icon to display in the button (for icon variant)
  enableHeaderClick = false, // NEW: enables header click to toggle checkbox
  onHeaderClick, // NEW: callback for header click
  footerButtonsConfig, // NEW: array of button configs for footer
  contextType = "default", // NEW: context type for default config (agent, tool, default)
  cardDisabled = false, // NEW: shows not-allowed cursor when user lacks access
}) => {
  const [checked, setChecked] = useState(isSelected);
  // New states for complex delete functionality
  const [isDeleteClicked, setIsDeleteClicked] = useState(false);
  const [deleteModal, setDeleteModal] = useState(false);
  const [emailId, setEmailId] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  // State for simple delete confirmation flip
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);

  // Get user info from cookies
  const loggedInUserEmail = Cookies.get("email");
  const userName = Cookies.get("userName");
  const role = Cookies.get("role");
  const loggedInDepartment = Cookies.get("department") || "";

  // Determine department badge variant
  const getDepartmentBadgeVariant = () => {
    if (!cardDepartment || cardDepartment === "Default") return "";
    if (loggedInDepartment && cardDepartment.toLowerCase() === loggedInDepartment.toLowerCase()) {
      return "badge-department-same";
    }
    return "badge-department-other";
  };

  useEffect(() => {
    if (enableComplexDelete) {
      userName === "Guest" ? setEmailId(cardCreatedBy || cardOwner) : setEmailId(loggedInUserEmail);
    }
  }, [userName, cardCreatedBy, cardOwner, loggedInUserEmail, enableComplexDelete]);

  // Sync checked state with isSelected prop
  useEffect(() => {
    setChecked(isSelected);
  }, [isSelected]);

  // Determine effective footer buttons config with unified logic
  let effectiveFooterButtons = footerButtonsConfig;
  if (!effectiveFooterButtons) {
    // Build from individual props if no config provided
    // Always respect explicit prop values - add buttons only when their prop is true
    effectiveFooterButtons = [];
    if (showDeleteButton) effectiveFooterButtons.push({ type: "delete", visible: true });
    if (showEditButton) effectiveFooterButtons.push({ type: "edit", visible: true });
    if (showChatButton) effectiveFooterButtons.push({ type: "chat", visible: true });
    if (showbutton) effectiveFooterButtons.push({ type: "view", visible: true });
    // Only fall back to contextType defaults if NO button props were explicitly handled
    // This ensures permission-based props (showDeleteButton=false) are respected
    if (effectiveFooterButtons.length === 0 && !onDeleteClick && !onEditClick && !onButtonClick && !onChatClick) {
      effectiveFooterButtons = card_config[contextType]?.footerButtons || card_config.default.footerButtons;
    }
  }

  // Updated for CheckBox component signature
  const handleCheckboxChange = (name, newChecked) => {
    setChecked(newChecked);
    if (onSelectionChange) {
      onSelectionChange(name, newChecked);
    }
  };

  const handleButtonClick = (e) => {
    e.stopPropagation(); // Prevent card click when button is clicked
    if (onButtonClick) {
      onButtonClick(cardName);
    }
  };

  const handleChatClick = (e) => {
    e.stopPropagation(); // Prevent card click when chat button is clicked
    if (onChatClick) {
      onChatClick(cardName);
    }
  };

  const handleDeleteClick = (e) => {
    e.stopPropagation(); // Prevent card click when delete button is clicked
    if (enableComplexDelete) {
      if (userName === "Guest") {
        setDeleteModal(true);
        return;
      }
      setErrorMessage("");
      setIsDeleteClicked(true);
    } else if (onDeleteClick) {
      // If skipDeleteConfirmation is true, call onDeleteClick directly without card flip
      if (skipDeleteConfirmation) {
        onDeleteClick(cardName);
      } else {
        // Show delete confirmation with flip animation instead of immediate callback
        setShowDeleteConfirmation(true);
      }
    }
  };

  const handleDeleteCancel = (e) => {
    e.stopPropagation();
    setShowDeleteConfirmation(false);
  };

  const handleDeleteConfirm = (e) => {
    e.stopPropagation();
    // Call the parent's delete callback with both cardName and cardData
    if (onDeleteClick) {
      onDeleteClick(cardName, cardData);
    }
    // Reset state after a brief delay to show the action
    setTimeout(() => {
      setShowDeleteConfirmation(false);
    }, 300);
  };

  const handleEditClick = (e) => {
    if (e && typeof e.stopPropagation === "function") {
      e.stopPropagation(); // Prevent card click when edit button is clicked
    }
    if (onEditClick) {
      onEditClick(cardData || { name: cardName, description: cardDescription });
    }
  };

  const handleComplexDeleteConfirm = () => {
    if (onComplexDelete) {
      const cardId = cardData?.id || cardData?.tool_id;
      if (!cardId) {
        setErrorMessage("Cannot delete: ID is missing");
        return;
      }
      onComplexDelete(cardId, emailId, role);
    }
  };

  const handleEmailChange = (e) => {
    setEmailId(e?.target?.value);
    setErrorMessage("");
  };

  // Function to get button configuration with icon and handler
  const getButtonConfig = (button) => {
    const buttonConfigs = {
      delete: {
        icon: enableComplexDelete ? "fa-solid fa-user-xmark" : "trash",
        title: "Delete",
        className: enableComplexDelete ? "complexDeleteBtn" : "delete-button",
        handler: handleDeleteClick,
        visible: showDeleteButton || (enableComplexDelete && !isRecycleMode),
      },
      info: {
        icon: "info-modern",
        title: "Info",
        className: "info-button",
        handler: (e) => {
          e.stopPropagation();
          if (typeof onInfoClick === "function") {
            onInfoClick(cardData);
          }
        },
        visible: typeof onInfoClick === "function",
      },
      view: {
        icon: "eye",
        title: "View",
        className: "info-button",
        handler: handleButtonClick,
        visible: showbutton || typeof onButtonClick === "function",
      },
      chat: {
        icon: "message-square",
        title: "Chat",
        className: "chat-button",
        handler: handleChatClick,
        visible: showChatButton,
      },
      edit: {
        icon: "edit",
        title: "Edit",
        className: "edit-button",
        handler: handleEditClick,
        visible: showEditButton,
      },
    };
    const config = buttonConfigs[button.type] || {};
    // Always use config.visible (prop-based) for permission-controlled buttons (delete, edit)
    // This ensures RBAC permissions are respected over card_config defaults
    const isVisible = config.visible || false;
    return {
      ...config,
      handler: button.handler || config.handler,
      visible: isVisible,
    };
  };

  const handleLoginButton = (e) => {
    e.preventDefault();
    if (onLoginRequired) {
      onLoginRequired();
    }
  };

  const handleCardClick = (e) => {
    // Don't trigger card click when showing delete confirmation
    if (showDeleteConfirmation) {
      return;
    }

    if (isRecycleMode && onEditClick) {
      handleEditClick(e);
    } else if (onCardClick) {
      onCardClick(e);
    }
  };

  // Helper function to truncate description based on word limit
  const getTruncatedDescription = (description) => {
    if (!description || truncateDescription === 0) return description;

    const words = description.split(" ");
    if (words.length <= truncateDescription) return description;

    return words.slice(0, truncateDescription).join(" ") + "...";
  };

  // Helper function to get display name with fallbacks
  const getDisplayName = () => {
    return cardName || cardData?.agentic_application_name || cardData?.tool_name || cardData?.name || "Unnamed Item";
  };

  // Optional: Enable header click to toggle checkbox (opt-in)
  const enableHeaderCheckboxToggle = Boolean(showcheckbox) && Boolean(onSelectionChange) && !isUnusedSection;
  const handleHeaderClick = (e) => {
    // Only toggle if enabled, and not disabled
    if (enableHeaderClick) {
      e.preventDefault();
      e.stopPropagation();
      if (onHeaderClick) {
        onHeaderClick(cardName, !checked);
      } else if (enableHeaderCheckboxToggle) {
        handleCheckboxChange(getDisplayName(), !checked);
      }
    }
  };

  // Helper function to get display description with fallbacks and truncation
  const getDisplayDescription = () => {
    const desc = cardDescription || cardData?.agentic_application_description || cardData?.tool_description || cardData?.description || "";
    return getTruncatedDescription(desc);
  };

  // Helper function to get card type for abbreviation
  const getCardType = () => {
    return cardType || cardData?.agentic_application_type || cardData?.tool_type || cardData?.type || "";
  };

  // Hover effect handlers
  const handleMouseEnter = (e) => {
    if (enableHoverEffects && !showDeleteConfirmation) {
      e.currentTarget.style.transform = hoverTransform;
      e.currentTarget.style.boxShadow = hoverShadow;
    }
  };

  const handleMouseLeave = (e) => {
    if (enableHoverEffects && !showDeleteConfirmation) {
      e.currentTarget.style.transform = "translateY(0)";
      e.currentTarget.style.boxShadow = normalShadow;
    }
  };

  // Helper function to determine if card footer should be rendered
  const shouldRenderFooter = () => {
    // Check if category should be shown
    const showCategory = cardCategory && cardCategory.toLowerCase() !== "uncategorized";

    // Check if department badge should be shown
    const showDepartment = Boolean(cardDepartment);

    // Check if any configured footer buttons are visible
    const hasVisibleButtons = effectiveFooterButtons.some((button) => {
      const config = getButtonConfig(button);
      return config.visible;
    });

    // Footer should render if there's a category, department, or any visible action button
    return showCategory || showDepartment || hasVisibleButtons;
  };

  return (
    <>
      {/* Delete Modal for unauthorized users */}
      {enableComplexDelete && (
        <DeleteModal show={deleteModal} onClose={() => setDeleteModal(false)}>
          {deleteModalContent || <p>You are not authorized to delete this item. Please login with registered email.</p>}
          <div className="modalButtonContainer">
            <button onClick={handleLoginButton} className="modalLoginBtn">
              Login
            </button>
            <button onClick={() => setDeleteModal(false)} className="modalCancelBtn">
              Cancel
            </button>
          </div>
        </DeleteModal>
      )}

      <div className={`card-container ${showDeleteConfirmation && !isListView ? "flipped" : ""}`}>
        <div
          className={`card card-with-checkbox ${customLayout !== "default" ? `card-layout-${customLayout}` : ""} ${cardDisabled ? "not-allowed-card" : onCardClick || (isRecycleMode && onEditClick) ? "clickable-card" : ""
            } ${isDeleteClicked ? "delete-mode" : ""} ${isRecycleMode ? "recycle-mode" : ""} ${isUnusedSection ? "unused-section" : ""} ${showDeleteConfirmation && isListView ? "show-inline-delete-confirmation" : ""
            } ${checked ? "selected" : ""}`}
          onClick={handleCardClick}
          onMouseEnter={!showDeleteConfirmation ? handleMouseEnter : undefined}
          onMouseLeave={!showDeleteConfirmation ? handleMouseLeave : undefined}
          style={
            enableHoverEffects
              ? {
                transition: "transform 0.2s ease, box-shadow 0.2s ease",
                boxShadow: normalShadow,
              }
              : {}
          }>
          {/* Inline delete confirmation for list view */}
          {showDeleteConfirmation && isListView && (
            <div className="inline-delete-confirmation">
              <div className="inline-delete-message">
                <SVGIcons icon="warnings" width={20} height={20} fill="#dc2626" />
                <p>This action cannot be undone.</p>
              </div>
              <div className="inline-delete-actions">
                <button onClick={handleDeleteCancel} className="inline-delete-cancel-btn">
                  Cancel
                </button>
                <button onClick={handleDeleteConfirm} className="inline-delete-confirm-btn">
                  Delete
                </button>
              </div>
            </div>
          )}

          {/* Normal card content */}
          {!isDeleteClicked && (!showDeleteConfirmation || !isListView) && (
            <>
              <div className="card-header">
                <div
                  className={`card-header-content ${checkboxPosition !== "left" ? `checkbox-${checkboxPosition}` : ""}`}
                  style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: enableHeaderClick || enableHeaderCheckboxToggle ? "pointer" : undefined }}
                  onClick={
                    enableHeaderCheckboxToggle
                      ? (e) => {
                        e.stopPropagation();
                        handleCheckboxChange(getDisplayName(), !checked);
                      }
                      : undefined
                  }>
                  {showcheckbox && checkboxPosition === "left" && (
                    <CheckBox
                      checked={checked}
                      onChange={(newChecked) => handleCheckboxChange(getDisplayName(), newChecked)}
                      className="card-checkbox"
                      id={`checkbox-${getDisplayName()}`}
                      label={getDisplayName()}
                      tabIndex={0}
                    />
                  )}
                  <Header name={getDisplayName()} onHeaderClick={handleHeaderClick} enableHeaderClick={enableHeaderClick} />
                  {showcheckbox && checkboxPosition === "right" && (
                    <CheckBox
                      checked={checked}
                      onChange={(newChecked) => handleCheckboxChange(getDisplayName(), newChecked)}
                      className="card-checkbox"
                      id={`checkbox-${getDisplayName()}`}
                      label={getDisplayName()}
                      tabIndex={0}
                    />
                  )}
                </div>
                {showcheckbox && checkboxPosition === "top" && (
                  <CheckBox
                    checked={checked}
                    onChange={(newChecked) => handleCheckboxChange(getDisplayName(), newChecked)}
                    className="card-checkbox checkbox-top"
                    id={`checkbox-${getDisplayName()}`}
                    label={getDisplayName()}
                    tabIndex={0}
                  />
                )}
              </div>

              {/* Description (conditionally rendered) */}
              {showDescription && <Description text={getDisplayDescription()} />}

              {/* Group/Role/Department Stats - Show members and agents count */}
              {["group", "role", "department"].includes(contextType) && (
                <div className="card-stats">
                  <div className="card-stat-item">
                    <SVGIcons icon="users" width={14} height={14} color="var(--content-color)" />
                    <span className="card-stat-value">
                      {cardData?.user_emails?.length || cardData?.users?.length || 0}
                    </span>
                    <span className="card-stat-label">Members</span>
                  </div>
                  <div className="card-stat-item">
                    <SVGIcons icon="cpu" width={14} height={14} color="var(--content-color)" />
                    <span className="card-stat-value">
                      {cardData?.agent_ids?.length || cardData?.agents?.length || 0}
                    </span>
                    <span className="card-stat-label">Agents</span>
                  </div>
                </div>
              )}

              {/* Type abbreviation (for agents, tools, etc.) */}
              {showTypeAbbreviation && getCardType() && (
                <div className="card-type-abbreviation" title={getTypeAbbreviation(getCardType(), "description", typeMappings)}>
                  {getTypeAbbreviation(getCardType(), "title", typeMappings)}
                </div>
              )}

              {/* Unused section specific info */}
              {isUnusedSection && (cardCreatedBy || cardCreatedOn || cardLastUsed) && (
                <div className="cardInfoSection">
                  {cardCreatedBy && (
                    <div className="infoItem">
                      <span className="infoLabel">Created by:</span> {cardCreatedBy}
                    </div>
                  )}
                  {cardCreatedOn && (
                    <div className="infoItem">
                      <span className="infoLabel">Created on:</span> {cardCreatedOn}
                    </div>
                  )}
                  {cardLastUsed && (
                    <div className="infoItem">
                      <span className="infoLabel">Last used:</span> {cardLastUsed}
                    </div>
                  )}
                </div>
              )}

              <div className="card-spacer"></div>

              {shouldRenderFooter() && (
                <div className="card-footer">
                  {cardCategory && cardCategory.toLowerCase() !== "uncategorized" && <Category category={cardCategory} />}
                  {cardDepartment && (
                    <span className={`card-badge ${getDepartmentBadgeVariant()}`} title={cardDepartment}>
                      {cardDepartment}
                    </span>
                  )}
                  {/* Fixed right-aligned action area for configurable buttons */}
                  <div className="cardActionsContainer">
                    {/* Render buttons in reverse order for right-to-left display */}
                    {effectiveFooterButtons
                      .slice()
                      .reverse()
                      .map((button, index) => {
                        const config = getButtonConfig(button);
                        if (!config.visible) return null;

                        return (
                          <button
                            key={`${button.type}-${index}`}
                            type="button"
                            className={config.className}
                            title={config.title}
                            onClick={config.handler}
                            aria-label={config.title}
                          >
                            <SVGIcons
                              icon={config.icon}
                              width={config.icon === "fa-solid fa-user-xmark" ? 20 : config.icon === "trash" ? 18 : config.icon === "info-modern" ? 16 : 20}
                              height={config.icon === "info-modern" ? 16 : 18}
                              color={config.icon === "eye" ? "var(--content-color)" : "currentColor"}
                            />
                          </button>
                        );
                      })}
                  </div>
                </div>
              )}
            </>
          )}

          {/* Delete confirmation mode */}
          {isDeleteClicked && enableComplexDelete && (
            <div className="deleteConfirmation">
              <button onClick={() => setIsDeleteClicked(false)} className="cancelDeleteBtn">
                <SVGIcons icon="fa-xmark" fill="#3D4359" />
              </button>

              <input type="text" value={cardCreatedBy || cardOwner || ""} disabled className="deleteEmailInput" />

              <div className="deleteWarningMessage">
                <SVGIcons icon="warnings" width={16} height={16} fill="#B8860B" />
                <span>creator / admin can perform this action</span>
              </div>

              {errorMessage && <p className="deleteErrorMessage">{errorMessage}</p>}

              <button onClick={handleComplexDeleteConfirm} className="deleteConfirmBtn">
                Delete <SVGIcons icon="fa-circle-xmark" width={16} height={16} />
              </button>
            </div>
          )}
        </div>

        {/* Delete Confirmation Back Side (Simple Delete) - Only in grid view */}
        {!isListView && (
          <div className="card card-back delete-confirmation-card">
            <div className="delete-confirmation-content">
              <div className="delete-warning-icon">
                <SVGIcons icon="warnings" width={48} height={48} fill="#dc2626" />
              </div>
              <h3 className="delete-confirmation-title">Delete {contextType === "server" ? "Server" : contextType === "agent" ? "Agent" : contextType === "group" ? "Group" : contextType === "role" ? "Role" : contextType === "department" ? "Department" : contextType === "pipeline" ? "Pipeline" : contextType === "resource" ? "Access Key" : contextType === "user" ? "User" : contextType === "knowledge base" ? "Knowledge Base" : "Tool"}?</h3>
              <p className="delete-confirmation-message">This action cannot be undone.</p>

              <div className="delete-confirmation-actions">
                <button onClick={handleDeleteCancel} className="delete-cancel-btn">
                  Cancel
                </button>
                <button onClick={handleDeleteConfirm} className="delete-confirm-btn">
                  Delete
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
};

export default Card;
