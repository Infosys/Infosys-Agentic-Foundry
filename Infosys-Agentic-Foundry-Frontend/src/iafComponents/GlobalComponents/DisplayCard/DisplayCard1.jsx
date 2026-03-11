import Card from "../Card/Card.jsx";
import SVGIcons from "../../../Icons/SVGIcons.js";
import { agentTypesDropdown } from "../../../constant.js";
import { formatDateTimeWithTimezone } from "../../../utils/timeFormatter";
import "./DisplayCard1.css";

// Helper function to get display label for agent type using existing dropdown config
const getAgentTypeLabel = (rawType) => {
  if (!rawType) return "Agent";

  // Find matching type in agentTypesDropdown array
  const matchedType = agentTypesDropdown.find((item) => item.value?.toLowerCase() === rawType.toLowerCase());

  if (matchedType?.label) {
    return matchedType.label;
  }

  // Fallback: convert snake_case to Title Case
  return rawType
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
};

const DisplayCard1 = ({
  data = [],
  onCardClick,
  onButtonClick,
  onDeleteClick,
  onChatClick,
  showCheckbox = false,
  onSelectionChange,
  showButton = false,
  buttonText = "⋯",
  showChatButton = false,
  showDeleteButton = false,
  skipDeleteConfirmation = false, // NEW: skip card's internal delete confirmation
  cardNameKey = "name",
  cardDescriptionKey = "description",
  cardOwnerKey = "created_by",
  cardCategoryKey = "category",
  emptyMessage = "No items to display",
  loading = false,
  className = "",
  // New props for enhanced card functionality
  showEditButton = false,
  onEditClick,
  isUnusedSection = false,
  isRecycleMode = false,
  enableComplexDelete = false,
  onComplexDelete,
  deleteModalContent,
  onLoginRequired, // NEW: Callback for info/eye icon button
  onInfoClick, // NEW: Callback for eye/info icon click
  buttonIcon, // NEW: Icon element to display in button (for icon variant)
  contextType = "tool", // NEW: "tool", "agent", "server" to determine create card text
  onCreateClick, // NEW: Callback for create new card click
  showCreateCard = true, // NEW: Whether to show the create card as first item
  footerButtonsConfig, // NEW: Array of button configs for footer
  selectedIds = [], // NEW: Array of selected item IDs
  idKey = "id", // NEW: Key to use for item ID comparison
  cardDisabled = false, // NEW: shows not-allowed cursor when user lacks access
}) => {
  // Helper function to safely get nested property values
  const getNestedValue = (obj, key) => {
    if (!obj || !key) return "";

    // Handle dot notation for nested properties
    if (key.includes(".")) {
      return key.split(".").reduce((value, k) => value?.[k], obj);
    }

    return obj[key];
  };

  // Helper function to get card name with fallbacks
  const getCardName = (item) => {
    // Try multiple possible name fields
    const nameFields = [cardNameKey, "tool_name", "agentic_application_name", "name", "title"];
    for (const field of nameFields) {
      const value = getNestedValue(item, field);
      if (value) return value;
    }
    return "Unnamed Item";
  };

  // Helper function to get card description with fallbacks
  const getCardDescription = (item) => {
    // Try multiple possible description fields
    const descFields = [cardDescriptionKey, "tool_description", "agentic_application_description", "description", "desc"];
    for (const field of descFields) {
      const value = getNestedValue(item, field);
      if (value) return value;
    }
    return "";
  };

  // Helper function to get card category with fallbacks
  // Returns the category/type for the card, handling tools, servers, agents, and knowledge bases
  const getCardCategory = (item) => {
    // If it's a server, prefer 'type' (local, remote, external)
    if (item.server_id || item.server_name) {
      return getNestedValue(item, "type") || "Server";
    }
    // If it's an agent, prefer 'type' and convert to display label
    if (item.agent_id || item.agentic_application_id || item.agent_name) {
      const rawType = getNestedValue(item, "type") || getNestedValue(item, "agent_type") || getNestedValue(item, "agentic_application_type");
      return getAgentTypeLabel(rawType);
    }
    // If it's a knowledge base
    if (item.kb_id || contextType === "knowledge base") {
      return getNestedValue(item, "type") || "KB";
    }
    // Otherwise, treat as tool (default logic)
    const categoryFields = [cardCategoryKey, "tool_type", "category", "type", "agentic_application_type"];
    for (const field of categoryFields) {
      const value = getNestedValue(item, field);
      if (value) return value;
    }
    return "TOOL";
  };

  // Helper function to get card owner
  const getCardOwner = (item) => {
    const ownerFields = [cardOwnerKey, "created_by", "owner", "author"];
    for (const field of ownerFields) {
      const value = getNestedValue(item, field);
      if (value) return value;
    }
    // Fallback: show 'Unknown' if no owner found
    return "";
  };

  // Helper function to get card department name
  const getCardDepartment = (item) => {
    // Check direct department fields first (for agents/tools)
    const departmentFields = ["department_name", "departmentName", "department", "raw.department_name"];
    for (const field of departmentFields) {
      const value = getNestedValue(item, field);
      if (value) return value;
    }

    // Check shared_with_departments array (for servers)
    const sharedDepartments = item?.shared_with_departments || item?.raw?.shared_with_departments;
    if (Array.isArray(sharedDepartments) && sharedDepartments.length > 0) {
      // Extract department name from array (could be strings or objects)
      const firstDept = sharedDepartments[0];
      if (typeof firstDept === "string") return firstDept;
      if (typeof firstDept === "object" && firstDept?.department_name) return firstDept.department_name;
    }

    return "Default";
  };

  // Helper function to get card created on date
  const getCardCreatedOn = (item) => {
    const createdOnFields = ["created_on", "createdOn", "created_at", "createdAt", "creation_date"];
    for (const field of createdOnFields) {
      const value = getNestedValue(item, field);
      if (value) return formatDateTimeWithTimezone(value) || value;
    }
    return "";
  };

  // Helper function to get card last used date
  const getCardLastUsed = (item) => {
    const lastUsedFields = ["last_used", "lastUsed", "last_used_at", "lastUsedAt", "last_activity"];
    for (const field of lastUsedFields) {
      const value = getNestedValue(item, field);
      if (value) return formatDateTimeWithTimezone(value) || value;
    }
    return "";
  };

  // Show loading state
  if (loading) {
    return <div className="display-card-loading">Loading...</div>;
  }

  // Show empty state only if no data AND no create card to show
  if ((!data || data.length === 0) && !showCreateCard) {
    return (
      <div className="display-card-empty">
        <div className="display-card-empty-message">{emptyMessage}</div>
      </div>
    );
  }

  // Check if we're in list view mode
  const isListView = className && className.includes("listView");

  // Get the appropriate label based on context type
  const getCreateLabel = () => {
    if (contextType === "agent") return "New Agent";
    if (contextType === "server") return "New Server";
    if (contextType === "validator") return "New Validator";
    if (contextType === "consistency") return "New Consistency";
    if (contextType === "group") return "New Group";
    if (contextType === "role") return "New Role";
    if (contextType === "department") return "New Department";
    if (contextType === "pipeline") return "New Pipeline";
    if (contextType === "resource") return "New Access Key";
    if (contextType === "user") return "New User";
    if (contextType === "knowledge base") return "New Knowledge Base";
    return "New Tool";
  };

  return (
    <div className={`display-cards-grid ${className}`}>
      <>
        {/* Create New Card - Always first */}
        {showCreateCard && (
          <div className="card-container" onClick={() => onCreateClick && onCreateClick()} style={{ cursor: "pointer" }}>
            <div className="card create-card">
              <div className="create-card-content">
                <div className="create-card-icon">
                  <SVGIcons icon="plus" width={20} height={20} color="var(--accent)" />
                </div>
                <div className="create-card-label">{getCreateLabel()}</div>
              </div>
            </div>
          </div>
        )}
        {data && data.length > 0 && data.map((item, index) => {
          const cardName = getCardName(item);
          // Use isUnusedSection to control showDescription
          const hideDescription = isUnusedSection === true;
          // Check if this item is selected
          const itemId = getNestedValue(item, idKey) || item.id || item.tool_id || item.agentic_application_id;
          const isSelected = selectedIds.includes(itemId);
          return (
            <Card
              key={`card-${index}-${item.id || item.tool_id || item.agentic_application_id || index}`}
              cardName={cardName}
              cardDescription={getCardDescription(item)}
              cardOwner={getCardOwner(item)}
              cardCategory={getCardCategory(item)}
              cardDepartment={getCardDepartment(item)}
              showcheckbox={showCheckbox}
              onSelectionChange={onSelectionChange}
              isSelected={isSelected}
              showbutton={["group", "role", "department"].includes(contextType) ? false : showButton}
              buttonText={buttonText}
              onButtonClick={["group", "role", "department"].includes(contextType) ? undefined : (onButtonClick ? () => onButtonClick(cardName, item) : undefined)}
              showChatButton={["group", "role", "department"].includes(contextType) ? false : showChatButton}
              onChatClick={() => onChatClick && onChatClick(cardName, item)}
              showDeleteButton={showDeleteButton}
              onDeleteClick={() => onDeleteClick && onDeleteClick(cardName, item)}
              skipDeleteConfirmation={skipDeleteConfirmation}
              onCardClick={() => onCardClick && onCardClick(cardName, item)}
              // Enhanced functionality props
              showEditButton={showEditButton}
              onEditClick={() => onEditClick && onEditClick(item)}
              isUnusedSection={isUnusedSection}
              isRecycleMode={isRecycleMode}
              enableComplexDelete={enableComplexDelete}
              onComplexDelete={onComplexDelete}
              deleteModalContent={deleteModalContent}
              onLoginRequired={onLoginRequired}
              // Data props for enhanced functionality
              cardData={item}
              cardCreatedBy={getCardOwner(item)}
              cardCreatedOn={getCardCreatedOn(item)}
              cardLastUsed={getCardLastUsed(item)}
              loading={loading}
              // List view mode
              isListView={isListView}
              showDescription={!hideDescription}
              onInfoClick={["group", "role", "department"].includes(contextType) ? undefined : (onInfoClick ? () => onInfoClick(item) : undefined)}
              buttonIcon={buttonIcon}
              contextType={contextType}
              footerButtonsConfig={footerButtonsConfig}
              cardDisabled={cardDisabled}
            />
          );
        })}
      </>
    </div>
  );
};

export default DisplayCard1;
