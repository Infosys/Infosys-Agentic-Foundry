import React from "react";
import "./Index.css";
import brandlogotwo from "../../Assets/Agentic-Foundry-Logo-Dark-2.png";
import SignUp from "./SignUp";
import { useVersion } from "../../context/VersionContext";
import { useTheme } from "../../Hooks/ThemeContext";
import SVGIcons from "../../Icons/SVGIcons";

const Register = ({ isAdminScreen = false }) => {
  const { combinedVersion } = useVersion();
  const { theme, toggleTheme } = useTheme();

  // If rendering inside admin screen, just return the form without wrapper
  if (isAdminScreen) {
    return <SignUp isAdminScreen={isAdminScreen} />;
  }

  // Otherwise, render the full page with background and logo
  return (
    <div className="app-container">
      <button
        className="authThemeToggle"
        title={theme === "light" ? "Switch to Dark Mode" : "Switch to Light Mode"}
        onClick={toggleTheme}
        aria-label="Toggle theme"
      >
        <SVGIcons
          icon={theme === "light" ? "dark-icon" : "light-icon"}
          width={18}
          height={18}
          fill="var(--text-primary)"
          stroke={theme === "light" ? "var(--app-primary-color)" : "var(--text-primary)"}
        />
      </button>
      <img src={brandlogotwo} alt="Brandlogo" />
      <div className="version_number" title={combinedVersion}>{combinedVersion}</div>
      <div className="div-login">
        <SignUp isAdminScreen={isAdminScreen} />
      </div>
    </div>
  );
}

export default Register;
