import React, { useState, useRef, useCallback } from "react";
import styles from "./AdminScreenNew.module.css";
import UserAssignmentUpdate from "./UserAssignmentUpdate";
import RecycleBin from "./RecycleBin";
import Unused from "./Unused";
import AgentLearning from "./AgentLearning";
import { APIs, agentTypesDropdown } from "../../constant";
import InstallationTab from "./InstallationTab";
import InferenceConfig from "./InferenceConfig";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios";
import SubHeader from "../commonComponents/SubHeader";
import SVGIcons from "../../Icons/SVGIcons";
import PageLayout from "../../iafComponents/GlobalComponents/PageLayout";
import GroupAgentAssignment from "./GroupAgentAssignment.jsx";
import RoleAgentAssignment from "./RoleAgentAssignment.jsx";
import UserManagement from "./UserManagement.jsx";
import ResourceAllocationManagement from "./ResourceAllocationManagement.jsx";

const AdminScreenNew = () => {
  const [activeTab, setActiveTab] = useState("userManagement");

  // Dropdown hover state for position calculation
  const [openDropdown, setOpenDropdown] = useState(null);
  const [dropdownPosition, setDropdownPosition] = useState({ top: 0, left: 0 });

  // Filter states
  const [selectedAgentTypes, setSelectedAgentTypes] = useState([]);
  const [selectedServerTypes, setSelectedServerTypes] = useState([]);
  const [selectedToolTypes, setSelectedToolTypes] = useState([]);

  // Search state for SubHeader
  const [searchValue, setSearchValue] = useState("");

  // COMMENTED OUT: State for "New Module" modal (Missing Modules tab)
  // const [showNewModuleModal, setShowNewModuleModal] = useState(false);

  // COMMENTED OUT: State for Missing Modules selection and install handler
  // const [missingModulesSelectedCount, setMissingModulesSelectedCount] = useState(0);
  // const installHandlerRef = useRef(null);

  // Refs for Group component handlers
  const groupPlusClickRef = useRef(null);
  const groupClearSearchRef = useRef(null);

  // Refs for Role component handlers
  const rolePlusClickRef = useRef(null);
  const roleClearSearchRef = useRef(null);

  // Refs for Resource Allocation component handlers
  const resourcePlusClickRef = useRef(null);
  const resourceClearSearchRef = useRef(null);

  // Resource Management navigation state (for hiding SubHeader in detail view)
  const [resourceNavState, setResourceNavState] = useState({
    isDetailView: false,
    keyName: null,
  });

  // Determine tab categories for conditional SubHeader configuration
  const isLearningTab = activeTab === "learningAllFeedbacks";
  // const isUserTab = activeTab === "register" || activeTab === "update";
  const isUserManagementTab = activeTab === "userManagement";
  const isAgentsTab = activeTab === "recycleBinAgents" || activeTab === "unusedAgents";
  const isToolsTab = activeTab === "recycleBinTools" || activeTab === "unusedTools";
  const isGroupTab = activeTab === "controlGroup";
  const isRoleTab = activeTab === "controlRole";
  const isServersTab = activeTab === "recycleBinServers" || activeTab === "unusedServers";
  const isResourceTab = activeTab === "resourceManagement";
  // Search enabled only for Installed and Pending modules (not Missing modules)
  const isInstallationTabWithSearch = activeTab === "installationInstalled" || activeTab === "installationPending";
  // Tabs that need search functionality (agents, tools, servers, installed/pending modules, user management, resource management, group, role)
  const needsSearch = isLearningTab || isAgentsTab || isToolsTab || isServersTab || isInstallationTabWithSearch || isUserManagementTab || isResourceTab || isGroupTab;

  // Handler for agent type filter
  const handleAgentTypeFilter = (e) => {
    setSelectedAgentTypes(e.target.value);
  };

  // Handler for server type filter
  const handleServerTypeFilter = (e) => {
    setSelectedServerTypes(e.target.value);
  };

  // Handler for tool type filter
  const handleToolTypeFilter = (e) => {
    setSelectedToolTypes(e.target.value);
  };

  // COMMENTED OUT: Handler for New Module button click
  // const handleNewModuleClick = () => {
  //   setShowNewModuleModal(true);
  // };

  // COMMENTED OUT: Handler for Missing Modules selection change
  // const handleMissingModulesSelectionChange = useCallback((count) => {
  //   setMissingModulesSelectedCount(count);
  // }, []);

  // COMMENTED OUT: Handler for receiving install function from InstallationTab
  // const handleInstallReady = useCallback((installFn) => {
  //   installHandlerRef.current = installFn;
  // }, []);

  // COMMENTED OUT: Handler for Install button click in SubHeader
  // const handleInstallClick = useCallback(() => {
  //   if (installHandlerRef.current) {
  //     installHandlerRef.current();
  //     // Reset selection count after install
  //     setMissingModulesSelectedCount(0);
  //   }
  // }, []);

  // Handle plus click for Group tab
  const handleGroupPlusClick = useCallback(() => {
    if (groupPlusClickRef.current) {
      groupPlusClickRef.current();
    }
  }, []);

  // Handle plus click for Role tab
  const handleRolePlusClick = useCallback(() => {
    if (rolePlusClickRef.current) {
      rolePlusClickRef.current();
    }
  }, []);

  // Handle plus click for Resource Allocation tab
  const handleResourcePlusClick = useCallback(() => {
    if (resourcePlusClickRef.current) {
      resourcePlusClickRef.current();
    }
  }, []);

  // Clear search handler for Group/Role/Resource tabs
  const clearSearchForControlTabs = useCallback(() => {
    setSearchValue("");
    if (isGroupTab && groupClearSearchRef.current) {
      groupClearSearchRef.current();
    }
    if (isRoleTab && roleClearSearchRef.current) {
      roleClearSearchRef.current();
    }
    if (isResourceTab && resourceClearSearchRef.current) {
      resourceClearSearchRef.current();
    }
  }, [isGroupTab, isRoleTab, isResourceTab]);

  // Get plus click handler based on active tab
  const getPlusClickHandler = () => {
    // if (isMissingModulesTab) return handleNewModuleClick;
    if (isGroupTab) return handleGroupPlusClick;
    if (isRoleTab) return handleRolePlusClick;
    if (isResourceTab) return handleResourcePlusClick;
    return null;
  };

  // Get plus button label based on active tab
  const getPlusButtonLabel = () => {
    // if (isMissingModulesTab) return "New Module";
    if (isGroupTab) return "New Group";
    if (isRoleTab) return "New Role";
    if (isResourceTab) return "New Access Key";
    return "";
  };

  // Navigation config for header dropdown menus - User first, Learning second, then others
  const navigationConfig = [
    {
      type: "section",
      key: "user",
      label: "User",
      children: [
        { key: "userAssignUpdate", label: "Assignment & Update" },
        { key: "userManagement", label: "Management" },
      ],
    },
    {
      type: "section",
      key: "learning",
      label: "Learning",
      children: [
        { key: "learningAllFeedbacks", label: "All Feedbacks" },
      ],
    },
    {
      type: "section",
      key: "installation",
      label: "Installation",
      children: [
        { key: "installationInstalled", label: "Installed Modules" },
        { key: "installationMissing", label: "Missing Modules" },
        { key: "installationPending", label: "Pending Modules" },
      ],
    },
    {
      type: "section",
      key: "recycleBin",
      label: "Recycle Bin",
      children: [
        { key: "recycleBinAgents", label: "Agents" },
        { key: "recycleBinTools", label: "Tools" },
        { key: "recycleBinServers", label: "Servers" },
      ],
    },
    {
      type: "section",
      key: "unused",
      label: "Unused",
      children: [
        { key: "unusedAgents", label: "Agents" },
        { key: "unusedTools", label: "Tools" },
        { key: "unusedServers", label: "Servers" },
      ],
    },
    {
      type: "section",
      key: "control",
      label: "Control",
      children: [
        { key: "controlGroup", label: "Group" },
        { key: "controlRole", label: "Role" },
      ],
    },
    {
      type: "section",
      key: "resource",
      label: "Resources",
      children: [
        { key: "resourceManagement", label: "Management" },
      ],
    },
    {
      type: "section",
      key: "configurations",
      label: "Config",
      children: [{ key: "inference", label: "Inference" }],
    },
  ];

  const handleNavClick = (key) => {
    setActiveTab(key);
    // Clear search when switching tabs
    setSearchValue("");
    // Clear all filter selections when switching tabs
    setSelectedAgentTypes([]);
    setSelectedServerTypes([]);
    setSelectedToolTypes([]);
  };

  // Get active label for SubHeader
  const getActiveLabel = () => {
    for (const section of navigationConfig) {
      if (section.children) {
        const child = section.children.find((c) => c.key === activeTab);
        if (child) return child.label;
      }
    }
    return "Admin";
  };

  // Get section label for breadcrumb
  const getSectionLabel = () => {
    for (const section of navigationConfig) {
      if (section.children) {
        const child = section.children.find((c) => c.key === activeTab);
        if (child) return section.label;
      }
    }
    return null;
  };

  const activeLabel = getActiveLabel();
  const sectionLabel = getSectionLabel();

  // Build breadcrumb items based on current navigation state
  const getBreadcrumbItems = () => {
    const items = [{ label: "Admin" }];

    // Add section label
    if (sectionLabel) {
      items.push({ label: sectionLabel });
    }

    // Add the tab label
    items.push({ label: activeLabel });

    return items;
  };

  const handleSearch = (value) => {
    setSearchValue(value);
  };

  const clearSearch = () => {
    setSearchValue("");
    // Clear all filters when search/filters are cleared
    setSelectedAgentTypes([]);
    setSelectedServerTypes([]);
    setSelectedToolTypes([]);
  };

  // Determine activeTab context for SubHeader based on current tab
  const getSubHeaderActiveTab = () => {
    if (isAgentsTab) return "agents";
    if (isToolsTab) return "tools";
    if (isServersTab) return "servers";
    // Check if any installation tab is active
    if (activeTab === "installationInstalled" || activeTab === "installationMissing" || activeTab === "installationPending") return "modules";
    if (isLearningTab) return "learning";
    return "admin";
  };

  // Check if a section has an active child tab
  const isSectionActive = (section) => {
    return section.children?.some((child) => child.key === activeTab);
  };

  // Ref for close timeout to allow moving to menu
  const closeTimeoutRef = useRef(null);

  // Handle dropdown hover - calculate position for fixed menu
  const handleDropdownEnter = (sectionKey, event) => {
    // Clear any pending close
    if (closeTimeoutRef.current) {
      clearTimeout(closeTimeoutRef.current);
      closeTimeoutRef.current = null;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    setDropdownPosition({
      top: rect.bottom,
      left: rect.left,
    });
    setOpenDropdown(sectionKey);
  };

  const handleDropdownLeave = () => {
    // Delay close to allow user to move mouse to menu
    closeTimeoutRef.current = setTimeout(() => {
      setOpenDropdown(null);
    }, 150);
  };

  // Keep menu open when hovering on it
  const handleMenuEnter = () => {
    if (closeTimeoutRef.current) {
      clearTimeout(closeTimeoutRef.current);
      closeTimeoutRef.current = null;
    }
  };

  const handleMenuLeave = () => {
    setOpenDropdown(null);
  };

  // Header navigation with dropdown menus (Amazon-style)
  const headerNav = (
    <nav className={styles.headerNav}>
      {navigationConfig.map((section) => (
        <div
          key={section.key}
          className={styles.navDropdown}
          onMouseEnter={(e) => handleDropdownEnter(section.key, e)}
          onMouseLeave={handleDropdownLeave}
        >
          <button
            className={`${styles.navDropdownTrigger} ${isSectionActive(section) ? styles.active : ""}`}
            aria-haspopup="true"
            aria-expanded={openDropdown === section.key}
          >
            {section.label}
            <SVGIcons icon="chevron-down" width={14} height={14} />
          </button>
          {openDropdown === section.key && (
            <div
              className={`${styles.navDropdownMenu} ${styles.open}`}
              style={{ top: dropdownPosition.top, left: dropdownPosition.left }}
              onMouseEnter={handleMenuEnter}
              onMouseLeave={handleMenuLeave}
            >
              {section.children?.map((child) => (
                <button
                  key={child.key}
                  className={`${styles.navDropdownItem} ${activeTab === child.key ? styles.active : ""}`}
                  onClick={() => handleNavClick(child.key)}
                >
                  {child.label}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </nav>
  );

  // Hide SubHeader when in resource detail view (user list for a key)
  const hideSubHeader = isResourceTab && resourceNavState.isDetailView;

  return (
    <div className="pageContainer">
      {!hideSubHeader && (
        <SubHeader
          heading=""
          activeTab={getSubHeaderActiveTab()}
          searchValue={searchValue}
          onSearch={handleSearch}
          clearSearch={isGroupTab || isRoleTab || isResourceTab ? clearSearchForControlTabs : clearSearch}
          showRefreshButton={false}
          showPlusButton={isGroupTab || isRoleTab}
          onPlusClick={getPlusClickHandler()}
          plusButtonLabel={getPlusButtonLabel()}
          // Secondary button for Missing Modules Install (commented out - isMissingModulesTab not defined)
          // secondaryButtonLabel={isMissingModulesTab ? "Install" : ""}
          // onSecondaryButtonClick={isMissingModulesTab ? handleInstallClick : null}
          // secondaryButtonDisabled={missingModulesSelectedCount === 0}
          // Show search for all content tabs
          showSearch={needsSearch}
          leftContent={headerNav}
          // Show agent type dropdown for Agents tabs (RecycleBin/Unused Agents) only
          showAgentTypeDropdown={isAgentsTab}
          agentTypes={agentTypesDropdown}
          selectedAgentType={isToolsTab ? selectedToolTypes : isServersTab ? selectedServerTypes : selectedAgentTypes}
          handleTypeFilter={isAgentsTab ? handleAgentTypeFilter : isServersTab ? handleServerTypeFilter : isToolsTab ? handleToolTypeFilter : null}
          // For Tools tabs, SubHeader auto-detects tool types via activeTab="tools"
          // No need for showTagsDropdown - we don't want Industry section
          showTagsDropdown={false}
          // Hide Created By dropdown
          showCreatedByDropdown={false}
          // Hide breadcrumb for admin screen - navigation is in header dropdowns
          breadcrumbItems={null}
        />
      )}

      {/* Main content area - render components directly to prevent re-mounting */}
      <PageLayout>
        {activeTab === "learningAllFeedbacks" && <AgentLearning searchValue={searchValue} selectedAgentTypes={selectedAgentTypes} />}
        {activeTab === "userAssignUpdate" && <UserAssignmentUpdate />}
        {activeTab === "userManagement" && <UserManagement externalSearchTerm={searchValue} />}
        {activeTab === "installationInstalled" && <InstallationTab searchValue={searchValue} type="installed" onClearSearch={clearSearch} />}
        {activeTab === "installationMissing" && (
          <InstallationTab
            searchValue={searchValue}
            type="missing"
            // COMMENTED OUT: New Module modal and selection/install functionality
            // externalShowModal={showNewModuleModal}
            // onExternalModalClose={() => setShowNewModuleModal(false)}
            // onSelectionChange={handleMissingModulesSelectionChange}
            // onInstallReady={handleInstallReady}
            onClearSearch={clearSearch}
          />
        )}
        {activeTab === "installationPending" && <InstallationTab searchValue={searchValue} type="pending" onClearSearch={clearSearch} />}
        {activeTab === "recycleBinAgents" && <RecycleBin initialType="agents" heading="Agents" externalSearchTerm={searchValue} selectedAgentTypes={selectedAgentTypes} />}
        {activeTab === "recycleBinTools" && <RecycleBin initialType="tools" heading="Tools" externalSearchTerm={searchValue} selectedToolTypes={selectedToolTypes} />}
        {activeTab === "recycleBinServers" && <RecycleBin initialType="servers" heading="Servers" externalSearchTerm={searchValue} selectedServerTypes={selectedServerTypes} />}
        {activeTab === "unusedAgents" && <Unused initialType="agents" heading="Agents" externalSearchTerm={searchValue} selectedAgentTypes={selectedAgentTypes} />}
        {activeTab === "unusedTools" && <Unused initialType="tools" heading="Tools" externalSearchTerm={searchValue} selectedToolTypes={selectedToolTypes} />}
        {activeTab === "controlGroup" && (
          <GroupAgentAssignment
            externalSearchTerm={searchValue}
            onPlusClickRef={groupPlusClickRef}
            onClearSearchRef={groupClearSearchRef}
            onClearParentSearch={clearSearch}
          />
        )}
        {activeTab === "controlRole" && (
          <RoleAgentAssignment
            externalSearchTerm={searchValue}
            onPlusClickRef={rolePlusClickRef}
            onClearSearchRef={roleClearSearchRef}
          />
        )}
        {activeTab === "unusedServers" && <Unused initialType="servers" heading="Servers" externalSearchTerm={searchValue} selectedServerTypes={selectedServerTypes} />}
        {activeTab === "resourceManagement" && (
          <ResourceAllocationManagement
            externalSearchTerm={searchValue}
            onPlusClickRef={resourcePlusClickRef}
            onClearSearchRef={resourceClearSearchRef}
            onNavigationChange={setResourceNavState}
          />
        )}
        {activeTab === "inference" && <InferenceConfig />}
      </PageLayout>
    </div>
  );
};

export default AdminScreenNew;
