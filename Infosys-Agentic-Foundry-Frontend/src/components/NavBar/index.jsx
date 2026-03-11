import { useState, useEffect, useRef } from "react";
import styles from "../../css_modules/NavBar.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { NavLink, useLocation } from "react-router-dom";
import { usePermissions } from "../../context/PermissionsContext";
import { useAuth } from "../../context/AuthContext";
import Cookies from "js-cookie";
import { emitActiveNavClick } from "../../events/navigationEvents";
import brandlogo from "../../Assets/Agentic-Foundry-Logo-Blue-2.png";
import { APIs, mkDocs_baseURL, grafanaDashboardUrl } from "../../constant";
import { useApiUrl } from "../../context/ApiUrlContext";
import { useVersion } from "../../context/VersionContext";
import useFetch from "../../Hooks/useAxios";
import { useMessage } from "../../Hooks/MessageContext";
import { useTheme } from "../../Hooks/ThemeContext";
import PermissionsModal from "./PermissionsModal";

export default function NavBar() {
  const [activeButton, setActiveButton] = useState("");
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showPermissionsModal, setShowPermissionsModal] = useState(false);
  const [isNavCollapsed, setIsNavCollapsed] = useState(true);
  const userMenuRef = useRef(null);
  const location = useLocation();
  const { user, role: authRole, logout, isAuthenticated } = useAuth();
  const { postData } = useFetch();
  const { addMessage } = useMessage();
  const { mkDocsInternalPath } = useApiUrl();
  const { combinedVersion } = useVersion();
  const displayName = user?.name || user || "";
  const role = authRole || Cookies.get("role");
  const department = Cookies.get("department") || "";
  const isAdmin = role && role.toUpperCase() === "ADMIN";
  const isSuperAdmin = role && role.toUpperCase() === "SUPERADMIN";
  const isUser = role && role.toUpperCase() === "USER";
  const { hasPermission } = usePermissions();
  const { theme, toggleTheme } = useTheme();

  // Permission-based visibility checks for navigation items
  // Using hasPermission(key, false) - if permission key not in API response, hide by default
  // Only show when permission explicitly exists and is true
  const canViewTools = hasPermission("read_access.tools", false);
  const canViewAgents = hasPermission("read_access.agents", false);
  const canAddTools = hasPermission("add_access.tools", false);
  const canUpdateTools = hasPermission("update_access.tools", false);
  const canViewDataConnectors = hasPermission("data_connector_access", false);
  const canViewEvaluation = hasPermission("evaluation_access", false);
  const canViewGroundTruth = hasPermission("evaluation_access", false);
  const canExecuteAgents = hasPermission("execute_access.agents", false);
  const canViewVault = hasPermission("vault_access", false);
  const canViewKnowledgeBase = hasPermission("knowledgebase_access", false);
  const canExecuteChat = hasPermission("execute_access.agents", false);

  // Compute if ALL permissions are OFF - user should only see Files
  const allPermissionsOff = !canViewTools && !canViewAgents && !canViewDataConnectors && !canViewEvaluation && !canViewGroundTruth && !canExecuteAgents && !canViewVault && !canViewKnowledgeBase && !canExecuteChat;

  // Set data attribute for collapsed state
  useEffect(() => {
    document.documentElement.setAttribute("data-nav-collapsed", "true");
    // --main-width is handled purely via CSS (:root and :root:has([data-nav]:hover))
  }, []);

  // Close user menu when clicking outside
  useEffect(() => {
    if (!showUserMenu) return;

    const handleClickOutside = (event) => {
      // Don't close if clicking inside the menu container
      if (userMenuRef.current && userMenuRef.current.contains(event.target)) {
        return;
      }
      setShowUserMenu(false);
    };

    // Add listener with a small delay to avoid catching the opening click
    const timer = setTimeout(() => {
      document.addEventListener("click", handleClickOutside);
    }, 10);

    return () => {
      clearTimeout(timer);
      document.removeEventListener("click", handleClickOutside);
    };
  }, [showUserMenu]);

  // Reset active button state when user logs out
  useEffect(() => {
    if (!isAuthenticated) {
      setActiveButton("");
    }
  }, [isAuthenticated]);

  // Close user menu when nav collapses (mouse leaves)
  // Use a ref-based approach to detect hover end
  const navRef = useRef(null);
  useEffect(() => {
    const navEl = navRef.current;
    if (!navEl) return;
    const handleMouseLeave = () => {
      if (showUserMenu) setShowUserMenu(false);
    };
    navEl.addEventListener("mouseleave", handleMouseLeave);
    return () => navEl.removeEventListener("mouseleave", handleMouseLeave);
  }, [showUserMenu]);

  // Close permissions modal when route changes
  useEffect(() => {
    setShowPermissionsModal(false);
  }, [location.pathname]);

  const handleNavClick = (e) => {
    // Reset active button state when navigating away from files
    if (activeButton === "files" && e !== "/files") {
      setActiveButton("");
    }
  };

  const handleLogout = async () => {
    try {
      await postData(APIs.LOGOUT);
    } catch (error) {
      addMessage("Logout request failed, but clearing local session.", "error");
    } finally {
      Cookies.remove("email");
      Cookies.remove("jwt-token");
      Cookies.remove("refresh-token");
      try {
        localStorage.removeItem("login_timestamp");
        Cookies.remove("login_timestamp");
      } catch (_) { }
      logout("manual");
    }
  };

  const handleGrafanaClick = () => {
    window.open(grafanaDashboardUrl, "_blank");
  };

  const handleHelpClick = () => {
    setShowUserMenu(false);
    window.open(mkDocs_baseURL + mkDocsInternalPath, "_blank");
  };

  const handlePermissionsClick = () => {
    setShowUserMenu(false);
    setShowPermissionsModal(true);
  };

  const handleLogoutClick = () => {
    setShowUserMenu(false);
    handleLogout();
  };

  const mainNavLink = (to, children, title = "", extraProps = {}) => {
    const handleClick = () => {
      handleNavClick(to);
      if (location.pathname === to) {
        emitActiveNavClick(to);
      }
    };
    return (
      <NavLink to={to} onClick={handleClick} className={({ isActive }) => (isActive ? styles.active : "")} title={title} {...extraProps}>
        {children}
      </NavLink>
    );
  };

  // If SuperAdmin, only show Super Admin nav item
  if (isSuperAdmin) {
    return (
      <div
        className={`${styles.navSection} ${styles.navCollapsed}`}
        ref={navRef}
        data-nav="true"
      >
        <div className={styles.navInner}>
          {/* Logo Section at Top */}
          <div className={styles.logoSection}>
            <img src={brandlogo} alt="Agentic Foundry" className={styles.logo} />
            <span className={styles.collapsedLogoText}>IAF</span>
            <div className={styles.versionInfo} title={combinedVersion}>
              {combinedVersion}
            </div>
          </div>
          <nav className={styles.nav}>
            <ul>
              {/* Super Admin panel - Only navigation item for SuperAdmin */}
              <li>
                {mainNavLink(
                  "/super-admin",
                  <>
                    <SVGIcons icon="person-circle" />
                    <span>Super Admin</span>
                  </>,
                  "Super Admin",
                )}
              </li>
            </ul>
          </nav>
          {/* Bottom User Section */}
          <div className={styles.bottomSection}>
            <div className={styles.topRow}>
              <div className={styles.userInfo}>
                <div className={styles.userName} title={`${displayName} (${role}${department ? ` - ${department}` : ""})`}>
                  {displayName}
                </div>
                <div className={styles.userRole}>{role}</div>
                {department && <div className={styles.userDepartment}>{department}</div>}
              </div>
              <div className={styles.userActionsContainer}>
                <button
                  className={styles.themeToggleBtn}
                  title={theme === "light" ? "Switch to Dark Mode" : "Switch to Light Mode"}
                  onClick={toggleTheme}
                >
                  <SVGIcons icon={theme === "light" ? "dark-icon" : "light-icon"} width={16} height={16} fill="var(--navbar-icon-color)" stroke={theme === "light" ? "var(--app-primary-color)" : "var(--text-primary)"} />
                </button>
                <div className={styles.userMenuContainer} ref={userMenuRef}>
                  <button
                    className={styles.userMenuButton}
                    title="User Menu"
                    aria-haspopup="true"
                    aria-expanded={showUserMenu}
                    onClick={() => setShowUserMenu(!showUserMenu)}>
                    <SVGIcons icon="fa-user" width={14} height={14} fill="var(--navbar-icon-color)" />
                  </button>
                  {showUserMenu && (
                    <div className={styles.userMenuPopover} role="menu" aria-label="User menu">
                      <button className={styles.menuItem} onClick={handleHelpClick} role="menuitem" tabIndex={0}>
                        <SVGIcons icon="fa-question" width={14} height={14} fill="var(--text-primary)" />
                        <span>Help</span>
                      </button>
                      <button className={`${styles.menuItem} ${styles.logoutMenuItem}`} onClick={handleLogoutClick} role="menuitem" tabIndex={0}>
                        <SVGIcons icon="logout" width={14} height={14} fill="var(--text-primary)" />
                        <span>Sign Out</span>
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
        {/* Permissions Modal */}
        <PermissionsModal isOpen={showPermissionsModal} onClose={() => setShowPermissionsModal(false)} />
      </div>
    );
  }

  return (
    <div
      className={`${styles.navSection} ${styles.navCollapsed}`}
      ref={navRef}
      data-nav="true"
    >
      {/* Inner scrollable container */}
      <div className={styles.navInner}>
        {/* Logo Section at Top */}
        <div className={styles.logoSection}>
          <img src={brandlogo} alt="Agentic Foundry" className={styles.logo} />
          <span className={styles.collapsedLogoText}>IAF</span>
          <div className={styles.versionInfo} title={combinedVersion}>
            {combinedVersion}
          </div>
        </div>
        {/* Main Navigation */}
        <nav className={styles.nav}>
          <ul>
            {/* Chat - Show based on execute_access.agents permission (Landing Page) */}
            {canExecuteAgents && (
              <li>
                {mainNavLink(
                  "/",
                  <>
                    <SVGIcons icon="nav-chat" />
                    <span>Chat</span>
                  </>,
                  "Chat",
                )}
              </li>
            )}

            {/* Tools - Always show in nav, access controlled at card level */}
            <li>
              {mainNavLink(
                "/tools",
                <>
                  <SVGIcons icon="fa-screwdriver-wrench" />
                  <span>Tools</span>
                </>,
                "Tools",
              )}
            </li>

            {/* Servers - Always show in nav, access controlled at card level */}
            <li>
              {mainNavLink(
                "/servers",
                <>
                  <SVGIcons icon="server" />
                  <span>Servers</span>
                </>,
                "Servers",
              )}
            </li>

            {/* Agents - Always show in nav, access controlled at card level */}
            <li>
              {mainNavLink(
                "/agent",
                <>
                  <SVGIcons icon="fa-robot" />
                  <span>Agents</span>
                </>,
                "Agents",
              )}
            </li>

            {/* Pipeline - Always show in nav, access controlled at card level */}
            <li>
              {mainNavLink(
                "/pipeline",
                <>
                  <SVGIcons icon="fa-project-diagram" />
                  <span>Pipeline</span>
                </>,
                "Pipeline",
              )}
            </li>

            {/* Vault/Secret - Show based on vault_access permission */}
            {canViewVault && (
              <li>
                {mainNavLink(
                  "/secret",
                  <>
                    <SVGIcons icon="vault-lock" />
                    <span>Vault</span>
                  </>,
                  "Vault",
                )}
              </li>
            )}

            {/* Data Connectors - Show based on data_connector_access permission */}
            {canViewDataConnectors && (
              <li>
                {mainNavLink(
                  "/dataconnector",
                  <>
                    <SVGIcons icon="data-connectors" />
                    <span>Data Connectors</span>
                  </>,
                  "Data Connectors",
                )}
              </li>
            )}

            {/* Knowledge Base - Show based on knowledge_base_access permission */}
            {canViewKnowledgeBase && (
              <li>
                {mainNavLink(
                  "/knowledge-base",
                  <>
                    <SVGIcons icon="knowledge-base" />
                    <span>Knowledge Base</span>
                  </>,
                  "Knowledge Base",
                )}
              </li>
            )}

            {/* Resource Dashboard - Show if user has tools create permission */}
            {canAddTools && (
              <li>
                {mainNavLink(
                  "/resource-dashboard",
                  <>
                    <SVGIcons icon="layout-grid" />
                    <span>Resource Dashboard</span>
                  </>,
                  "Resource Dashboard",
                )}
              </li>
            )}

            {/* Evaluation - Show for non-USER roles based on evaluation_access permission */}
            {canViewEvaluation && (
              <li>
                {mainNavLink(
                  "/evaluation",
                  <>
                    <SVGIcons icon="clipboard-check" />
                    <span>Evaluation</span>
                  </>,
                  "Evaluation",
                )}
              </li>
            )}

            {/* Admin - Show only for Admin role */}
            {isAdmin && (
              <li>
                {mainNavLink(
                  "/admin",
                  <>
                    <SVGIcons icon="person-circle" />
                    <span>Admin</span>
                  </>,
                  "Admin",
                )}
              </li>
            )}

            {/* Files - Always visible */}
            <li>
              {mainNavLink(
                "/files",
                <>
                  <SVGIcons icon="file" />
                  <span>Files</span>
                </>,
                "Files",
              )}
            </li>
          </ul>
        </nav>

        {/* Bottom User Section */}
        <div className={styles.bottomSection}>
          <div className={styles.topRow}>
            <div className={styles.userInfo}>
              <div className={styles.userName} title={displayName === "Guest" ? displayName : `${displayName} (${role}${department ? ` - ${department}` : ""})`}>
                {displayName === "Guest" ? "Guest" : displayName}
              </div>
              {displayName !== "Guest" && <div className={styles.userRole}>{role}</div>}
              {displayName !== "Guest" && department && <div className={styles.userDepartment}>{department}</div>}
            </div>
            <div className={styles.userActionsContainer}>
              <button
                type="button"
                className={styles.themeToggleBtn}
                title={theme === "light" ? "Switch to Dark Mode" : "Switch to Light Mode"}
                onClick={toggleTheme}
              >
                <SVGIcons icon={theme === "light" ? "dark-icon" : "light-icon"} width={16} height={16} fill="var(--navbar-icon-color)" stroke={theme === "light" ? "var(--app-primary-color)" : "var(--text-primary)"} />
              </button>
              <div
                ref={userMenuRef}
                className={styles.userMenuContainer}
                onMouseEnter={() => setShowUserMenu(true)}
                onMouseLeave={() => setShowUserMenu(false)}
              >
                <button
                  type="button"
                  className={styles.userMenuButton}
                  title="User Menu"
                  aria-haspopup="true"
                  aria-expanded={showUserMenu}
                >
                  <SVGIcons icon="fa-user" width={14} height={14} fill="var(--navbar-icon-color)" />
                </button>
                {showUserMenu && (
                  <div className={styles.userMenuPopover} role="menu" aria-label="User menu">
                    <button className={styles.menuItem} onClick={handlePermissionsClick} role="menuitem" tabIndex={0}>
                      <SVGIcons icon="vault-lock" width={14} height={14} color="var(--text-primary)" />
                      <span>Permissions</span>
                    </button>
                    <button className={styles.menuItem} onClick={handleHelpClick} role="menuitem" tabIndex={0}>
                      <SVGIcons icon="fa-question" width={14} height={14} fill={"var(--text-primary)"} />
                      <span>Help</span>
                    </button>
                    <button className={styles.menuItem} onClick={handleGrafanaClick} role="menuitem" tabIndex={0}>
                      <SVGIcons icon="grafana" width={14} height={14} />
                      <span>Grafana</span>
                    </button>
                    <button className={`${styles.menuItem} ${styles.logoutMenuItem}`} onClick={handleLogoutClick} role="menuitem" tabIndex={0}>
                      <SVGIcons icon="logout" width={14} height={14} fill="var(--text-primary)" />
                      <span>Sign Out</span>
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
        {/* Permissions Modal */}
        <PermissionsModal isOpen={showPermissionsModal} onClose={() => setShowPermissionsModal(false)} />
      </div>
      {/* End of navInner */}
    </div>
  );
}
