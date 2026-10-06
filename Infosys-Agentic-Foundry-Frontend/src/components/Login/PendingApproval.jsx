import React from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useVersion } from "../../context/VersionContext";
import { useTheme } from "../../Hooks/ThemeContext";
import { exitSsoOnboardingToLogin } from "../../auth/msalSessionUtils";
import brandlogotwo from "../../Assets/Agentic-Foundry-Logo-Dark-2.png";
import SVGIcons from "../../Icons/SVGIcons";
import styles from "./PendingApproval.module.css";
import "./app.css";
import "./login.css";

/**
 * PendingApproval — static info page shown after a new SSO user submits their
 * department request (or when the backend detects a pending registration).
 *
 * Backend redirects here as:
 *   /pending-approval?email=user@example.com
 */
function PendingApproval() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { combinedVersion } = useVersion();
  const { theme, toggleTheme } = useTheme();

  const email = searchParams.get("email") || "";

  const handleBackToLogin = async () => {
    await exitSsoOnboardingToLogin();
    navigate("/login", { replace: true });
  };

  return (
    <div className="app-container">
      <img src={brandlogotwo} alt="Agentic Foundry" />
      <div className="version_number" title={combinedVersion}>
        {combinedVersion}
      </div>

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

      <div className={styles.centeredWrapper}>
        <div className={styles.card}>
          {/* Icon */}
          <div className={styles.iconCircle}>
            <SVGIcons icon="history-clock" width={28} height={28} stroke="#f59e0b" />
          </div>

          <h2 className={styles.title}>Access Pending Approval</h2>

          <p className={styles.body}>
            Your account registration has been submitted successfully. An
            administrator will review and approve your request shortly.
          </p>

          {email && (
            <div className={styles.emailBadge}>
              <SVGIcons icon="at-sign" width={13} height={13} fill="currentColor" />
              <span>{email}</span>
            </div>
          )}

          <div className={styles.infoBox}>
            <SVGIcons
              icon="exclamation"
              width={15}
              height={15}
              fill="currentColor"
            />
            <p>
              Once approved, you can log in normally. If you haven't heard back
              within 24 hours, please contact your administrator.
            </p>
          </div>

          <button
            type="button"
            className="submitBtn"
            onClick={handleBackToLogin}
          >
            <span style={{ display: "inline-flex", transform: "rotate(180deg)" }}>
              <SVGIcons icon="arrow-right" width={14} height={14} stroke="currentColor" />
            </span>
            Back to Login
          </button>
        </div>
      </div>
    </div>
  );
}

export default PendingApproval;
