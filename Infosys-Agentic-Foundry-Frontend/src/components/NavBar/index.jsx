import React, { useState, useEffect } from "react";
import styles from "../../css_modules/NavBar.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { NavLink, useLocation } from "react-router-dom";
import { useGlobalComponent } from "../../Hooks/GlobalComponentContext";
import { useAuth } from "../../context/AuthContext";
import { usePermissions } from "../../context/PermissionsContext";
import Cookies from "js-cookie";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faKey, faProjectDiagram } from "@fortawesome/free-solid-svg-icons";
import { emitActiveNavClick } from "../../events/navigationEvents";

export default function NavBar() {
  const { showComponent, hideComponent } = useGlobalComponent();
  const [activeButton, setActiveButton] = useState("");
  const location = useLocation();
  const { isAuthenticated } = useAuth();

  const role = Cookies.get("role");
  const isAdmin = role && role.toLowerCase() === "admin";
  const isDeveloper = role && role.toLowerCase() === "developer";
  const isUser = role && role.toLowerCase() === "user";
  const { permissions, hasPermission } = usePermissions();



  // Reset active button state when user logs out
  useEffect(() => {
    if (!isAuthenticated) {
      setActiveButton("");
    }
  }, [isAuthenticated]);

  const handleNavClick = (e) => {
    if (activeButton === "files" && e !== "/files") {
      hideComponent();
      setActiveButton("");
    }
  };

  const handleFileClick = () => {
    setActiveButton("files");
    showComponent(<div>Your file content here</div>);
  };

  const mainNavLink = (to, children, extraProps = {}) => {
    const handleClick = () => {
      handleNavClick(to);
      if (location.pathname === to) {
        emitActiveNavClick(to);
      }
    };
    return (
      <NavLink
        to={to}
        onClick={handleClick}
        className={({ isActive }) => (isActive ? "active" : "")}
        {...extraProps}
      >
        {children}
      </NavLink>
    );
  };

  return (
    <div className={styles.navSection}>
      <nav className={styles.nav}>
        <ul>
          {/* If role is 'user' show only Chat, Files, Ground Truth. Other roles follow existing permission logic. */}
          { !isUser && (
            <>
              {(typeof hasPermission === "function" ? hasPermission("read_access.tools") : !(permissions && permissions.read_access && permissions.read_access.tools === false)) && (
                <li>
                  {mainNavLink(
                    "/",
                    <>
                      <SVGIcons icon="fa-screwdriver-wrench" fill="#343741" />
                      <span>Tools</span>
                    </>
                  )}
                </li>
              )}
              {(typeof hasPermission === "function" ? hasPermission("read_access.agents") : !(permissions && permissions.read_access && permissions.read_access.agents === false)) && (
                <li>
                  {mainNavLink(
                    "/agent",
                    <>
                      <SVGIcons icon="fa-robot" fill="#343741" />
                      <span>Agents</span>
                    </>
                  )}
                </li>
              )}
              {(typeof hasPermission === "function" ? hasPermission("read_access.agents") : !(permissions && permissions.read_access && permissions.read_access.agents === false)) && (
                <li>
                  {mainNavLink(
                    "/pipeline",
                    <>
                      <FontAwesomeIcon icon={faProjectDiagram} />
                      <span>Pipeline</span>
                    </>
                  )}
                </li>
              )}
            </>
          )}
          <li>
            {mainNavLink(
              "/chat",
              <>
                <SVGIcons icon="nav-chat" fill="#343741" />
                <span>Chat</span>
              </>
            )}
          </li>
          {/* Vault and Data Connectors are not shown for simple users */}
          { !isUser && (
            <>
              {(typeof hasPermission === "function" ? hasPermission("vault_access") : !(permissions && permissions.vault_access === false)) && (
                <li>
                  {mainNavLink(
                    "/secret",
                    <>
                      <FontAwesomeIcon icon={faKey} />
                      <span>Secret</span>
                    </>
                  )}
                </li>
              )}
              {(typeof hasPermission === "function" ? hasPermission("data_connector_access") : !(permissions && permissions.data_connector_access === false)) && (
                <li>
                  {mainNavLink(
                    "/dataconnector",
                    <>
                      <SVGIcons icon="data-connectors" fill="#343741" />
                      <span>Data Connectors</span>
                    </>
                  )}
                </li>
              )}
            </>
          )}
          <li>
            <button onClick={handleFileClick} className={activeButton === "files" ? "active" : ""}>
              <SVGIcons icon="file" fill="#343741" />
              <span>Files</span>
            </button>
          </li>
          {/* Ground Truth should be visible to simple users as requested. Non-user roles keep existing visibility (current logic made it hidden for admin/dev). */}
          { (
              isUser || (!isAdmin && !isDeveloper)
            ) && (
            <li>
              {mainNavLink(
                "/groundtruth",
                <>
                  <SVGIcons icon="ground-truth" color="#343741" />
                  <span>Ground Truth Evaluation</span>
                </>
              )}
            </li>
          )}
          {/* Show Admin nav only if user is admin (case-insensitive) */}
          {((role && role.toUpperCase() === "ADMIN") || isDeveloper )&& (
            <li>
              {mainNavLink(
                "/evaluation",
                <>
                  <SVGIcons icon="clipboard-check" fill="#343741" />
                  <span>Evaluation</span>
                </>
              )}
            </li>
          )}
              {role && role.toUpperCase() === "ADMIN" && (
                <li>
                  {mainNavLink(
                    "/admin",
                    <>
                      <SVGIcons icon="person-circle" fill="#343741" />
                      <span>Admin</span>
                    </>
                  )}
            </li>
          )}
        </ul>
      </nav>
    </div>
  );
}