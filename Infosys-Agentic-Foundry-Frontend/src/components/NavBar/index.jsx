import React, { useState, useEffect } from "react";
import styles from "../../css_modules/NavBar.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { NavLink, useLocation } from "react-router-dom";
import { useGlobalComponent } from "../../Hooks/GlobalComponentContext";
import { useAuth } from "../../context/AuthContext";
import Cookies from "js-cookie";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faKey } from "@fortawesome/free-solid-svg-icons";
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
          {/* Hide Tools, Agents, Vault for USER role */}
          {!isUser && (
            <>
              <li>
                {mainNavLink(
                  "/",
                  <>
                    <SVGIcons icon="fa-screwdriver-wrench" fill="#343741" />
                    <span>Tools</span>
                  </>
                )}
              </li>
              <li>
                {mainNavLink(
                  "/agent",
                  <>
                    <SVGIcons icon="fa-robot" fill="#343741" />
                    <span>Agents</span>
                  </>
                )}
              </li>
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
          {/* Vault should be below Chat */}
          {!isUser && (
            <li>
              {mainNavLink(
                "/secret",
                <>
                  <FontAwesomeIcon icon={faKey} />
                  <span>Vault</span>
                </>
              )}
            </li>
          )}
          {!isUser && (
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
          <li>
            <button onClick={handleFileClick} className={activeButton === "files" ? "active" : ""}>
              <SVGIcons icon="file" fill="#343741" />
              <span>Files</span>
            </button>
          </li>
          {(!isAdmin && !isDeveloper) && (
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
