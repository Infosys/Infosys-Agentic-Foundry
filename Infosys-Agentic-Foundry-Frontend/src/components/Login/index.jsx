import React from "react";
import "./app.css";
import brandlogotwo from "../../Assets/Agentic-Foundry-Logo-Dark-2.png";
import LoginScreen from "./LoginScreen";
import { useVersion } from "../../context/VersionContext";
import { useTheme } from "../../Hooks/ThemeContext";
import SVGIcons from "../../Icons/SVGIcons";

function Login() {
  const { combinedVersion } = useVersion();
  const { theme, toggleTheme } = useTheme();

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
        <LoginScreen />
      </div>
    </div>
  );
}

export default Login;
