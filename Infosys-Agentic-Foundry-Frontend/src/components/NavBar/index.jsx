/* global ReactRouterDOM */
import React, { useState } from "react";
import styles from "../../css_modules/NavBar.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { NavLink } from "react-router-dom";
import { useGlobalComponent } from "../../Hooks/GlobalComponentContext";
import Cookies from "js-cookie";

export default function NavBar() {
  const { showComponent } = useGlobalComponent();
  const [activeButton, setActiveButton] = useState("");

  const role = Cookies.get("role");

  const handleFileClick = () => {
    setActiveButton("files");
    showComponent(<div>Your file content here</div>);
  };
  return (
    <div className={styles.navSection}>
      <nav className={styles.nav}>
        <ul>
          <li>
            <NavLink  to="/" activeclassname="active">
              <SVGIcons icon="fa-screwdriver-wrench" fill="#343741" />
              <span>Tools</span>
            </NavLink>
          </li>
          <li>
            <NavLink to="/agent" activeclassname="active">
              <SVGIcons icon="fa-robot" fill="#343741" />
              <span>Agents</span>
            </NavLink>
          </li>
          <li>
            <NavLink to="/chat" activeclassname="active">
              <SVGIcons icon="nav-chat" fill="#343741"/>
              <span>Chat</span>
            </NavLink>
          </li>
          {/* <li>
            <NavLink to="/dataconnector" activeclassname="active">
              <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="currentColor" viewBox="0 0 24 24">
    <path d="M12 2C6.48 2 2 4.24 2 7v10c0 2.76 4.48 5 10 5s10-2.24 10-5V7c0-2.76-4.48-5-10-5zm0 2c4.41 0 8 1.57 8 3s-3.59 3-8 3-8-1.57-8-3 3.59-3 8-3zm0 16c-4.41 0-8-1.57-8-3v-1.17c1.83 1.11 5.06 1.67 8 1.67s6.17-.56 8-1.67V17c0 1.43-3.59 3-8 3zm0-5c-4.41 0-8-1.57-8-3v-1.17c1.83 1.11 5.06 1.67 8 1.67s6.17-.56 8-1.67V12c0 1.43-3.59 3-8 3zm0-5c-4.41 0-8-1.57-8-3V7.83c1.83 1.11 5.06 1.67 8 1.67s6.17-.56 8-1.67V8c0 1.43-3.59 3-8 3z"/>
  </svg>
              <span>Data</span>
            </NavLink>
          </li> */}
          <li>
            <button onClick={handleFileClick}
              className={activeButton === "files" ? "active" : ""}
            >
              <SVGIcons icon="file" fill="#343741" />
              <span>Files</span>
            </button>
          </li>
          {/* <li>
            <NavLink to="/new-chat" activeclassname="active">
              <SVGIcons icon="new-chat" fill="#343741"/>
              <span>New Chat</span>
            </NavLink>
          </li> */}
          {/* Show Admin nav only if user is admin (case-insensitive) */}
          {role && role.toUpperCase() === "ADMIN" && (
            <>
            <li>
              <NavLink to="/admin" activeclassname="active">
                <SVGIcons icon="person-circle" fill="#343741"/>
                <span>Admin</span>
              </NavLink>
            </li>
            </>
          )}
        </ul>
      </nav>
    </div>
  );
}