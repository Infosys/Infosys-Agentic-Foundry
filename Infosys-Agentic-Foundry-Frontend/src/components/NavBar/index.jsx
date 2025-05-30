/* global ReactRouterDOM */
import React, { useState } from "react";
import styles from "../../css_modules/NavBar.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { NavLink } from "react-router-dom";
import { useGlobalComponent } from "../../Hooks/GlobalComponentContext";

export default function NavBar() {
  const { showComponent } = useGlobalComponent();
  const [activeButton, setActiveButton] = useState(null);

  const handleFileClick = () => {
    setActiveButton("files");
    showComponent(<div>Your file content here</div>);
  };
  return (
    <div className={styles.navSection}>
      <nav className={styles.nav}>
        <ul>
          <li>
            <NavLink exact to="/" activeClassName="active">
              <SVGIcons icon="fa-screwdriver-wrench" fill="#343741" />
              <span>Tools</span>
            </NavLink>
          </li>
          <li>
            <NavLink to="/agent" activeClassName="active">
              <SVGIcons icon="fa-robot" fill="#343741" />
              <span>Agents</span>
            </NavLink>
          </li>
          <li>
            <NavLink to="/chat" activeClassName="active">
              <SVGIcons icon="nav-chat" fill="#343741"/>
              <span>Chat</span>
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
        </ul>
      </nav>
    </div>
  );
}