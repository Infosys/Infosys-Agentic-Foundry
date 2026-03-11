import React from "react";
import SVGIcons from "../../Icons/SVGIcons";
import styles from "./SubHeader.module.css";
import UnifiedFilterDropdown from "./UnifiedFilterDropdown";
import Cookies from "js-cookie";
import DeleteModal from "./DeleteModal";
import { useAuth } from "../../context/AuthContext";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import TextField from "../../iafComponents/GlobalComponents/TextField/TextField";
import Breadcrumb from "./Breadcrumb";

// Stable default values defined outside component to prevent new references on each render
const EMPTY_ARRAY = [];
const NOOP = () => { };

const SubHeader = (props) => {
  const {
    onPlusClick,
    heading,
    activeTab,
    handleRefresh,
    clearSearch,
    showAgentTypeDropdown = false,
    agentTypes,
    selectedAgentType = "",
    handleTypeFilter,
    showTagsDropdown = false,
    availableTags,
    selectedTagsForDropdown,
    onTagsChange,
    showMyItemsFilter = false,
    myItemsChecked = false,
    onMyItemsChange,
    myItemsLabel = "My Items",

    // Created By dropdown
    createdBy = "All",
    onCreatedByChange,
    showCreatedByDropdown = false,

    // Secondary button props
    secondaryButtonLabel = "",
    onSecondaryButtonClick,
    secondaryButtonDisabled = false,
    secondaryButtonTitle = "",

    // Control visibility of refresh and plus buttons
    showRefreshButton = true,
    showPlusButton = true,

    // Control visibility of search field
    showSearch = true,

    // Custom button label (overrides context-based label)
    plusButtonLabel = "",

    // Left content slot (for hamburger menu button, etc.)
    leftContent = null,

    // Breadcrumb navigation - array of items [{label: string, onClick?: function}]
    breadcrumbItems = null,
    breadcrumbSeparator = "/",

    // Custom content slot to render left of the search field (e.g., department dropdown)
    searchLeftContent = null,
    // Show inline type filter (inside industry/agents dropdown instead of separate section)
    showInlineTypeFilter = false,

    // Agent type metadata for showing type badges
    agentTypeMetadata = {},
  } = props;

  // Use stable references for array/function props to prevent infinite loops
  const stableAgentTypes = agentTypes || EMPTY_ARRAY;
  const stableAvailableTags = availableTags || EMPTY_ARRAY;
  const stableSelectedTags = selectedTagsForDropdown || EMPTY_ARRAY;
  const stableHandleTypeFilter = handleTypeFilter || NOOP;
  const stableOnTagsChange = onTagsChange || NOOP;
  const stableOnMyItemsChange = onMyItemsChange || NOOP;
  const stableOnCreatedByChange = onCreatedByChange || NOOP;
  const stableOnSecondaryButtonClick = onSecondaryButtonClick || NOOP;

  // Normalize heading and activeTab to lowercase for consistent comparisons
  const normalizedHeading = heading?.toLowerCase() || "";
  const normalizedActiveTab = activeTab?.toLowerCase() || "";

  // Context helper booleans for cleaner conditional logic
  const isServersContext = normalizedHeading === "servers" || normalizedActiveTab === "servers";
  const isAgentsContext = normalizedHeading === "agents" || normalizedActiveTab === "agents";
  const isToolsContext = normalizedHeading === "tools" || normalizedActiveTab === "tools";
  const isPipelinesContext = normalizedHeading === "pipelines" || normalizedActiveTab === "pipelines";
  const isMetricsContext = normalizedActiveTab === "metrics" || normalizedActiveTab === "evaluation";
  const isVaultContext = normalizedHeading === "vault" || normalizedActiveTab === "vault";
  const isConsistencyContext = normalizedHeading === "consistency" || normalizedActiveTab === "consistency";
  const isResponsesContext = normalizedHeading === "responses" || normalizedActiveTab === "responses";
  const isModulesContext = normalizedActiveTab === "modules" || normalizedHeading.includes("modules");

  // Local state for tags dropdown selection - use stable reference
  const [localTags, setLocalTags] = React.useState([]);

  // Sync local tags with prop only when values actually change (deep comparison)
  React.useEffect(() => {
    const incomingTags = stableSelectedTags;
    setLocalTags((prevTags) => {
      // Compare by value to prevent unnecessary updates
      if (prevTags.length === incomingTags.length && prevTags.every((tag, i) => tag === incomingTags[i])) {
        return prevTags; // No change, return same reference
      }
      return incomingTags;
    });
  }, [stableSelectedTags]);

  // Local state for search input
  const [localSearch, setLocalSearch] = React.useState(props.searchValue || "");

  // Keep local state in sync with parent if searchValue changes externally
  React.useEffect(() => {
    const newValue = props.searchValue || "";
    setLocalSearch((prev) => (prev === newValue ? prev : newValue));
  }, [props.searchValue]);

  // Local state for type filter
  const [selectedTypes, setSelectedTypes] = React.useState([]);

  // Initialize selected types from prop
  React.useEffect(() => {
    if (selectedAgentType !== null && selectedAgentType !== void 0) {
      if (Array.isArray(selectedAgentType)) {
        setSelectedTypes(selectedAgentType);
      } else if (selectedAgentType !== "") {
        setSelectedTypes([selectedAgentType]);
      } else {
        setSelectedTypes([]);
      }
    }
  }, [selectedAgentType]);

  // Determine dropdown options based on context
  const getTypeOptions = () => {
    if (isServersContext) {
      return [
        { value: "external", label: "External" },
        { value: "local", label: "Local" },
        { value: "remote", label: "Remote" },
      ];
    }

    if (isToolsContext) {
      return [
        { value: "tool", label: "Tools" },
        { value: "validator", label: "Validator" },
      ];
    }

    // Include agent types when explicitly enabled OR for agents/metrics context
    if (showAgentTypeDropdown || ((isAgentsContext || isMetricsContext) && showInlineTypeFilter)) {
      return stableAgentTypes.filter((type) => type.value !== "");
    }

    return [];
  };

  const typeOptions = getTypeOptions();
  const showTypeDropdown = typeOptions.length > 0;

  // Determine placeholder based on context
  const getSearchPlaceholder = () => {
    if (isAgentsContext) return "Search Agents";
    if (isServersContext) return "Search Servers";
    if (isToolsContext) return "Search Tools";
    if (isPipelinesContext) return "Search Pipelines";
    if (isVaultContext) return "Search Secrets";
    if (isConsistencyContext) return "Search Consistencies";
    if (isMetricsContext) return "Search Consistencies";
    if (isResponsesContext) return "Search Responses";
    if (isModulesContext) return "Search Modules";
    return "Search";
  };

  // Get button label based on context
  const getButtonLabel = () => {
    if (plusButtonLabel) return plusButtonLabel;
    if (isServersContext) return "New Server";
    if (isAgentsContext) return "New Agent";
    return "New Tool";
  };

  // Get context type for toast messages and filter labels
  const getContextType = () => {
    if (isServersContext) return "Servers";
    if (isAgentsContext) return "Agents";
    if (isToolsContext) return "Tools";
    if (isMetricsContext) return "Metrics";
    return "Items";
  };

  const userName = Cookies.get("userName");

  const [showAddModal, setShowAddModal] = React.useState(false);

  const handlePlusClick = () => {
    if (userName === "Guest") {
      setShowAddModal(true);
      return;
    }
    if (typeof onPlusClick === "function") {
      onPlusClick();
      return;
    }
  };

  const { logout } = useAuth();

  const handleLoginButton = (e) => {
    e.preventDefault();
    logout("/login");
  };

  return (
    <>
      <DeleteModal show={showAddModal} onClose={() => setShowAddModal(false)}>
        <p>You are not authorized to add/modify. Please login with registered email.</p>
        {handleRefresh && (
          <div className={styles.buttonContainer}>
            <button onClick={(e) => handleLoginButton(e)} className={styles.loginBtn}>
              Login
            </button>
            <button onClick={() => setShowAddModal(false)} className={styles.cancelBtn}>
              Cancel
            </button>
          </div>
        )}
      </DeleteModal>
      <div className={styles.container}>
        <div className={styles.titleContainer}>
          {leftContent}
          {breadcrumbItems && breadcrumbItems.length > 0 ? <Breadcrumb items={breadcrumbItems} separator={breadcrumbSeparator} /> : <h6>{heading}</h6>}
          {showRefreshButton && (
            <button
              type="button"
              onClick={() => {
                if (typeof handleRefresh === "function") handleRefresh();
              }}
              title={"Refresh"}
              className={styles.refreshButton}>
              <SVGIcons icon="refresh-new" width={16} height={16} color="var(--content-color)" />
            </button>
          )}
        </div>

        <div className={styles.rightPart}>
          {/* Unified Filter Dropdown - combines Type, Tags/Industry, and Created By */}
          {(showTypeDropdown || showTagsDropdown || showCreatedByDropdown) && (
            <UnifiedFilterDropdown
              typeOptions={typeOptions}
              selectedTypes={selectedTypes}
              onTypeChange={(newTypes) => {
                // Only update local state, don't trigger API call
                setSelectedTypes(newTypes);
              }}
              industryOptions={stableAvailableTags}
              selectedIndustries={localTags}
              onIndustryChange={(newTags) => {
                // Only update local state, don't trigger API call
                setLocalTags(newTags);
              }}
              createdByOptions={showCreatedByDropdown ? ["All", "Me"] : []}
              selectedCreatedBy={createdBy}
              onCreatedByChange={stableOnCreatedByChange}
              contextType={getContextType()}
              industryLabel={isMetricsContext ? "Agents" : "Industry"}
              showInlineTypeFilter={showInlineTypeFilter}
              agentTypeMetadata={agentTypeMetadata}
              onApply={(appliedTypes, appliedTags, appliedCreatedBy) => {
                // Receive fresh values directly from dropdown's staged state
                // Pass types, tags, and createdBy to avoid stale state issues

                // Trigger API call with all parameters
                if (onTagsChange) {
                  // Pass tags, types, and createdBy to handleFilter
                  stableOnTagsChange(appliedTags, appliedTypes, appliedCreatedBy);
                } else if (handleTypeFilter) {
                  // Fallback if no tag handler exists
                  stableHandleTypeFilter({ target: { value: appliedTypes } }, appliedCreatedBy);
                }
              }}
              onClear={() => {
                // Clear local SubHeader state
                setSelectedTypes([]);
                setLocalTags([]);
                setLocalSearch("");

                // Use handleRefresh as the single source of truth for clearing all filters
                // handleRefresh resets ALL state (search, tags, types, createdBy) and fetches fresh data
                // This avoids race conditions from calling multiple state setters that trigger API calls
                if (handleRefresh) {
                  handleRefresh();
                } else {
                  // Fallback: manually reset createdBy to maintain consistent behavior
                  if (onCreatedByChange) {
                    stableOnCreatedByChange("All");
                  }
                  // Clear search if handler provided
                  if (clearSearch) {
                    clearSearch();
                  }
                }
              }}
            />
          )}
          {/* Custom content slot left of search (e.g., department dropdown) */}
          {searchLeftContent}
          {/* Search field using TextField component */}
          {showSearch && (
            <div className={styles.searchFieldWrapper}>
              <TextField
                placeholder={getSearchPlaceholder()}
                value={localSearch}
                onChange={(e) => {
                  setLocalSearch(e.target.value);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") props.onSearch(localSearch);
                }}
                onClear={() => {
                  setLocalSearch("");
                  props.onSearch("");
                }}
                showClearButton={true}
                showSearchButton={true}
                onSearch={() => props.onSearch(localSearch)}
                aria-label={getSearchPlaceholder()}
              />
            </div>
          )}
          {/* {onSettingClick && (
          <button type="button" onClick={handleSettingClick} className={styles.setting}>
            {selectedTags?.length > 0 && <span className={styles.badge}>{selectedTags?.length}</span>}
            <SVGIcons icon="slider-rect" width={20} height={18} fill="#C3C1CF" />
          </button>
            )} */}

          {secondaryButtonLabel && (
            <IAFButton
              type="secondary"
              onClick={onSecondaryButtonClick}
              className="subheaderExportBtn"
              title={secondaryButtonTitle}
              icon={
                <SVGIcons
                  icon="upload-new"
                  fill={secondaryButtonDisabled ? "var(--disabled-bg)" : "var(--secondary-bg)"}
                  color={secondaryButtonDisabled ? "var(--disabled-text)" : "var(--content-color)"}
                  width={16}
                  height={16}
                />
              }
              disabled={secondaryButtonDisabled}>
              {secondaryButtonLabel}
            </IAFButton>
          )}
          {showPlusButton && (
            <IAFButton
              type="primary"
              onClick={handlePlusClick}
              aria-label={getButtonLabel()}
              icon={<SVGIcons icon="fa-plus" fill="#FFF" width={16} height={16} className={styles.plusIcon} style={{ marginRight: "12px" }} />}>
              {getButtonLabel()}
            </IAFButton>
          )}
        </div>
      </div>
      {showMyItemsFilter && (
        <div className={styles.secondRow}>
          <div className={styles.myItemsFilter}>
            <button
              type="button"
              role="checkbox"
              aria-checked={myItemsChecked}
              data-state={myItemsChecked ? "checked" : "unchecked"}
              className={styles.myItemsCheckbox}
              id="my-items-filter"
              onClick={() => stableOnMyItemsChange(!myItemsChecked)}>
              {myItemsChecked && (
                <span className={styles.checkboxIndicator}>
                  <SVGIcons icon="check" width={14} height={14} stroke="currentColor" fill="none" strokeWidth={2} />
                </span>
              )}
            </button>
            <label htmlFor="my-items-filter" className={styles.myItemsLabel}>
              {myItemsLabel}
            </label>
          </div>
        </div>
      )}
    </>
  );
};

export default SubHeader;
