import React, { useState, useRef, useCallback, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import styles from "./AdminScreenNew.module.css";
import RoleAgentAssignment from "./RoleAgentAssignment.jsx";
import SubHeader from "../commonComponents/SubHeader";
import SVGIcons from "../../Icons/SVGIcons";
import PageLayout from "../../iafComponents/GlobalComponents/PageLayout";
import DepartmentManagement from "./DepartmentManagement.jsx";
import UserManagement from "./UserManagement.jsx";
import InstallationTab from "./InstallationTab";
import UserAssignmentUpdate from "./UserAssignmentUpdate";
import NotificationPanel from "./NotificationPanel";
import notifStyles from "./NotificationPanel.module.css";
import ChatHistoryCleanup from "./ChatHistoryCleanup";
import TokenUsageTracking from "./TokenUsageTracking";
import ModelCosts from "./ModelCosts";
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";

const SuperAdminControl = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeTab, setActiveTab] = useState("userAssignUpdate");
  const [showNotifications, setShowNotifications] = useState(false);

  // Notification data — fetched once on mount and refreshable
  const [notifRequests, setNotifRequests] = useState([]);
  const [notifLoading, setNotifLoading] = useState(false);
  const { fetchData } = useFetch();

  const loadNotifications = useCallback(async () => {
    setNotifLoading(true);
    try {
      const response = await fetchData(APIs.GET_REGISTRATION_REQUESTS);
      const list =
        response?.requests ?? response?.data?.requests ?? (Array.isArray(response) ? response : []);
      setNotifRequests(list);
    } catch {
      setNotifRequests([]);
    } finally {
      setNotifLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadNotifications();
  }, [loadNotifications]);

  // Legacy URLs used ?tab=super_admins — redirect to User Management
  useEffect(() => {
    const tabParam = searchParams.get("tab");
    if (tabParam === "super_admins") {
      setActiveTab("userManagement");
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const notifPendingCount = notifRequests.filter(
    (r) => r.status?.toLowerCase() === "pending"
  ).length;

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

  // Ref for Model Costs component handler
  const modelCostsPlusClickRef = useRef(null);

  // Ref for Cleanup tab handler
  const cleanupRunClickRef = useRef(null);
  const tokenDownloadClickRef = useRef(null);
  const [tokenReportDownloading, setTokenReportDownloading] = useState(false);

  const isDepartmentTab = activeTab === "controlDepartment";
  const isRoleTab = activeTab === "controlRole";
  const isModelCostsTab = activeTab === "modelCosts";
  const isCleanupTab = activeTab === "chatHistoryCleanup";
  const isTokenUsageTab = activeTab === "tokenUsageTracking";
  const isUserManagementTab = activeTab === "userManagement";
  const isInstallationTabWithSearch = activeTab === "installationInstalled" || activeTab === "installationPending";
  const needsSearch = isUserManagementTab || isInstallationTabWithSearch;

  // Navigation config for SuperAdmin - matching Admin's horizontal dropdown pattern
  const navigationConfig = [
    {
      type: "section",
      key: "user",
      label: "User",
      children: [
        { key: "userAssignUpdate", label: "Update" },
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
    {
      type: "section",
      key: "maintenance",
      label: "Maintenance",
      children: [
        { key: "chatHistoryCleanup", label: "Cleanup" },
      ],
    },
    {
      type: "section",
      key: "reports",
      label: "Reports",
      children: [
        { key: "tokenUsageTracking", label: "Token Usage" },
        { key: "modelCosts", label: "Model Costs" },
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

  // Handle plus click for Model Costs tab
  const handleModelCostsPlusClick = useCallback(() => {
    if (modelCostsPlusClickRef.current) {
      modelCostsPlusClickRef.current();
    }
  }, []);

  const handleCleanupRunClick = useCallback(() => {
    if (cleanupRunClickRef.current) {
      cleanupRunClickRef.current();
    }
  }, []);

  const getPlusClickHandler = () => {
    if (isDepartmentTab) return handleDeptPlusClick;
    if (isRoleTab) return handleRolePlusClick;
    if (isModelCostsTab) return handleModelCostsPlusClick;
    if (isCleanupTab) return handleCleanupRunClick;
    return null;
  };

  const getPlusButtonLabel = () => {
    if (isDepartmentTab) return "New Department";
    if (isRoleTab) return "New Role";
    if (isModelCostsTab) return "Add Model Cost";
    if (isCleanupTab) return "Run Cleanup";
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
      {navigationConfig.map((item) => {
        if (item.type === "link") {
          return (
            <div key={item.key} className={styles.navDropdown}>
              <button
                type="button"
                className={`${styles.navDropdownTrigger} ${activeTab === item.key ? styles.active : ""}`}
                onClick={() => handleNavClick(item.key)}
              >
                {item.label}
              </button>
            </div>
          );
        }

        return (
          <div
            key={item.key}
            className={styles.navDropdown}
            onMouseEnter={(e) => handleDropdownEnter(item.key, e)}
            onMouseLeave={handleDropdownLeave}
          >
            <button
              className={`${styles.navDropdownTrigger} ${isSectionActive(item) ? styles.active : ""}`}
              aria-haspopup="true"
              aria-expanded={openDropdown === item.key}
            >
              {item.label}
              <SVGIcons icon="chevron-down" width={14} height={14} />
            </button>
            {openDropdown === item.key && (
              <div
                className={`${styles.navDropdownMenu} ${styles.open}`}
                style={{ top: dropdownPosition.top, left: dropdownPosition.left }}
                onMouseEnter={handleMenuEnter}
                onMouseLeave={handleMenuLeave}
              >
                {item.children?.map((child) => (
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
        );
      })}
    </nav>
  );

  return (
    <div className="pageContainer">
      <SubHeader
        heading=""
        activeTab={getSubHeaderActiveTab()}
        searchValue={searchValue}
        onSearch={handleSearch}
        clearSearch={clearSearch}
        showRefreshButton={false}
        showPlusButton={isDepartmentTab || isRoleTab || isModelCostsTab || isCleanupTab}
        onPlusClick={getPlusClickHandler()}
        plusButtonLabel={getPlusButtonLabel()}
        quaternaryButtonLabel={isTokenUsageTab ? "Download Report" : ""}
        onQuaternaryButtonClick={isTokenUsageTab ? () => tokenDownloadClickRef.current?.() : undefined}
        quaternaryButtonDisabled={isTokenUsageTab && tokenReportDownloading}
        quaternaryButtonIcon="download"
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
          <UserManagement externalSearchTerm={searchValue} includeSuperAdminRoleFilter />
        )}
        {activeTab === "controlDepartment" && (
          <DepartmentManagement
            onPlusClickRef={deptPlusClickRef}
            onClearSearchRef={deptClearSearchRef}
          />
        )}
        {activeTab === "controlRole" && (
          <RoleAgentAssignment
            onPlusClickRef={rolePlusClickRef}
            onClearSearchRef={roleClearSearchRef}
          />
        )}
        {activeTab === "installationInstalled" && <InstallationTab searchValue={searchValue} type="installed" onClearSearch={clearSearch} />}
        {activeTab === "installationMissing" && <InstallationTab searchValue={searchValue} type="missing" onClearSearch={clearSearch} />}
        {activeTab === "installationPending" && <InstallationTab searchValue={searchValue} type="pending" onClearSearch={clearSearch} />}
        {activeTab === "chatHistoryCleanup" && <ChatHistoryCleanup onRunClickRef={cleanupRunClickRef} />}
        {activeTab === "tokenUsageTracking" && (
          <TokenUsageTracking
            onDownloadClickRef={tokenDownloadClickRef}
            onDownloadingChange={setTokenReportDownloading}
          />
        )}
        {activeTab === "modelCosts" && <ModelCosts onPlusClickRef={modelCostsPlusClickRef} />}
      </PageLayout>

      {/* Floating Notification Button */}
      <button
        type="button"
        className={`${notifStyles.floatingNotifBtn} ${showNotifications ? notifStyles.floatingNotifBtnHidden : ""}`}
        onClick={() => setShowNotifications(true)}
        aria-label="Notifications"
      >
        <SVGIcons icon="bell" width={24} height={24} />
        {notifPendingCount > 0 && (
          <span className={notifStyles.floatingBadge}>{notifPendingCount}</span>
        )}
      </button>

      {/* Notification Panel */}
      {showNotifications && (
        <NotificationPanel
          onClose={() => setShowNotifications(false)}
          requests={notifRequests}
          loading={notifLoading}
          onRefresh={loadNotifications}
        />
      )}
    </div>
  );
};

export default SuperAdminControl;