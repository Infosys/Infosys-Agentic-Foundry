import React, { useState, useRef, useCallback } from "react";
import styles from "./AdminScreenNew.module.css";
import RoleAgentAssignment from "./RoleAgentAssignment.jsx";
import SubHeader from "../commonComponents/SubHeader";
import SVGIcons from "../../Icons/SVGIcons";
import PageLayout from "../../iafComponents/GlobalComponents/PageLayout";
import DepartmentManagement from "./DepartmentManagement.jsx";
import UserManagement from "./UserManagement.jsx";
import InstallationTab from "./InstallationTab";
import UserAssignmentUpdate from "./UserAssignmentUpdate";

const SuperAdminControl = () => {
  const [activeTab, setActiveTab] = useState("userAssignUpdate");

  // Dropdown hover state for position calculation
  const [openDropdown, setOpenDropdown] = useState(null);
  const [dropdownPosition, setDropdownPosition] = useState({ top: 0, left: 0 });

  // Search state for SubHeader
  const [searchValue, setSearchValue] = useState("");

  // Refs for Department component handlers
  const deptPlusClickRef = useRef(null);
  const deptClearSearchRef = useRef(null);

  // Refs for Role component handlers
  const rolePlusClickRef = useRef(null);
  const roleClearSearchRef = useRef(null);

  // Determine tab categories for conditional SubHeader configuration
  const isDepartmentTab = activeTab === "controlDepartment";
  const isRoleTab = activeTab === "controlRole";
  const isUserManagementTab = activeTab === "userManagement";
  const isInstallationTabWithSearch = activeTab === "installationInstalled" || activeTab === "installationPending";
  // Tabs that need search functionality
  const needsSearch = isUserManagementTab || isInstallationTabWithSearch || isDepartmentTab || isRoleTab;

  // Navigation config for SuperAdmin - matching Admin's horizontal dropdown pattern
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
      key: "control",
      label: "Control",
      children: [
        { key: "controlRole", label: "Role" },
        { key: "controlDepartment", label: "Department" },
      ],
    },
  ];

  const handleNavClick = (key) => {
    setActiveTab(key);
    // Clear search when switching tabs
    setSearchValue("");
  };

  const handleSearch = (value) => {
    setSearchValue(value);
  };

  const clearSearch = () => {
    setSearchValue("");
  };

  // Clear search handler for Department/Role tabs
  const clearSearchForControlTabs = useCallback(() => {
    setSearchValue("");
    if (isDepartmentTab && deptClearSearchRef.current) {
      deptClearSearchRef.current();
    }
    if (isRoleTab && roleClearSearchRef.current) {
      roleClearSearchRef.current();
    }
  }, [isDepartmentTab, isRoleTab]);

  // Handle plus click for Department tab
  const handleDeptPlusClick = useCallback(() => {
    if (deptPlusClickRef.current) {
      deptPlusClickRef.current();
    }
  }, []);

  // Handle plus click for Role tab
  const handleRolePlusClick = useCallback(() => {
    if (rolePlusClickRef.current) {
      rolePlusClickRef.current();
    }
  }, []);

  // Get plus click handler based on active tab
  const getPlusClickHandler = () => {
    if (isDepartmentTab) return handleDeptPlusClick;
    if (isRoleTab) return handleRolePlusClick;
    return null;
  };

  // Get plus button label based on active tab
  const getPlusButtonLabel = () => {
    if (isDepartmentTab) return "New Department";
    if (isRoleTab) return "New Role";
    return "";
  };

  // Determine activeTab context for SubHeader based on current tab
  const getSubHeaderActiveTab = () => {
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
    closeTimeoutRef.current = setTimeout(() => {
      setOpenDropdown(null);
    }, 150);
  };

  const handleMenuEnter = () => {
    if (closeTimeoutRef.current) {
      clearTimeout(closeTimeoutRef.current);
      closeTimeoutRef.current = null;
    }
  };

  const handleMenuLeave = () => {
    setOpenDropdown(null);
  };

  // Header navigation with dropdown menus (same as Admin screen)
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

  return (
    <div className="pageContainer">
      <SubHeader
        heading=""
        activeTab={getSubHeaderActiveTab()}
        searchValue={searchValue}
        onSearch={handleSearch}
        clearSearch={isDepartmentTab || isRoleTab ? clearSearchForControlTabs : clearSearch}
        showRefreshButton={false}
        showPlusButton={isDepartmentTab || isRoleTab}
        onPlusClick={getPlusClickHandler()}
        plusButtonLabel={getPlusButtonLabel()}
        showSearch={needsSearch}
        leftContent={headerNav}
        showAgentTypeDropdown={false}
        showTagsDropdown={false}
        showCreatedByDropdown={false}
        breadcrumbItems={null}
      />

      {/* Main content area - render components directly to prevent re-mounting */}
      <PageLayout>
        {activeTab === "userAssignUpdate" && <UserAssignmentUpdate />}
        {activeTab === "userManagement" && (
          <UserManagement externalSearchTerm={searchValue} />
        )}
        {activeTab === "controlDepartment" && (
          <DepartmentManagement
            externalSearchTerm={searchValue}
            onPlusClickRef={deptPlusClickRef}
            onClearSearchRef={deptClearSearchRef}
          />
        )}
        {activeTab === "controlRole" && (
          <RoleAgentAssignment
            externalSearchTerm={searchValue}
            onPlusClickRef={rolePlusClickRef}
            onClearSearchRef={roleClearSearchRef}
          />
        )}
        {activeTab === "installationInstalled" && <InstallationTab searchValue={searchValue} type="installed" onClearSearch={clearSearch} />}
        {activeTab === "installationMissing" && <InstallationTab searchValue={searchValue} type="missing" onClearSearch={clearSearch} />}
        {activeTab === "installationPending" && <InstallationTab searchValue={searchValue} type="pending" onClearSearch={clearSearch} />}
      </PageLayout>
    </div>
  );
};

export default SuperAdminControl;
