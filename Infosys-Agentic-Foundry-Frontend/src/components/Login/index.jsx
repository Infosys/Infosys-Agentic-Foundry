import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import "./app.css";
import brandLogoDark from "../../Assets/Agentic-Foundry-Logo-Dark-2.png";
import brandLogoLight from "../../Assets/Agentic-Foundry-Logo-Blue-2.png";
import LoginScreen from "./LoginScreen";
import { useVersion } from "../../context/VersionContext";
import { useTheme } from "../../Hooks/ThemeContext";
import SVGIcons from "../../Icons/SVGIcons";
import { isMsalLoginPending, clearMsalAuthInProgress, hasPendingMsalRedirect, isMsalAuthInProgress } from "../../auth/msalSessionUtils";
import MsalAuthLoader from "../commonComponents/MsalAuthLoader";

function Login() {
  const { combinedVersion } = useVersion();
  const { theme, toggleTheme } = useTheme();
  const [searchParams] = useSearchParams();
  const msalError = searchParams.get("msalError");
  const [ready, setReady] = useState(false);

  // Stale MSAL in-progress flag (e.g. interrupted redirect) can block the login page with a blank loader
  useEffect(() => {
    if (msalError || (isMsalAuthInProgress() && !hasPendingMsalRedirect())) {
      clearMsalAuthInProgress();
    }
    setReady(true);
  }, [msalError]);

  if (!ready) {
    return <MsalAuthLoader />;
  }

  if (!msalError && isMsalLoginPending()) {
    return <MsalAuthLoader />;
  }

  const brandLogo = theme === "dark" ? brandLogoDark : brandLogoLight;

  return (
    <div className={`app-container ${theme === "light" ? "app-container-light" : ""}`}>
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
      <img src={brandLogo} alt="Brandlogo" />
      <div className="version_number" title={combinedVersion}>{combinedVersion}</div>
      <div className="div-login">
        <LoginScreen />
      </div>
    </div>
  );
}

export default Login;