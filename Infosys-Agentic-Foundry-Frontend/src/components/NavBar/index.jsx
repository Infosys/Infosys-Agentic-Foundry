/* global ReactRouterDOM */
import React, { useState } from "react";
import styles from "../../css_modules/NavBar.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { NavLink } from "react-router-dom";
import { useGlobalComponent } from "../../Hooks/GlobalComponentContext";
import Cookies from "js-cookie";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faKey } from "@fortawesome/free-solid-svg-icons";

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
           <li>
            <NavLink to="/secret" activeclassname="active">
              <FontAwesomeIcon icon={faKey}/>
              <span>Vault</span>
            </NavLink>
          </li>
          <li>
            <NavLink to="/groundtruth" activeclassname="active">
              <SVGIcons icon="ground-truth" color="#343741" />
              <span>Ground Truth</span>
            </NavLink>
          </li>
          <li>
            <NavLink to="/dataconnector" activeclassname="active">
             <SVGIcons icon="data-connectors" fill="#343741"/>
              <span>Data Connectors</span>
            </NavLink>
          </li>
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