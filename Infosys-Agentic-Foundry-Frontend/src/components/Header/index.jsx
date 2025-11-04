import React from "react";
import styles from "../../css_modules/Header.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import brandlogotwo from "../../Assets/Agentic-Foundry-Logo-Blue-2.png";
import { useNavigate } from "react-router-dom";
import Cookies from "js-cookie";
import { APIs, mkDocs_baseURL } from "../../constant";
import { useApiUrl } from "../../context/ApiUrlContext"; // Import the hook
import { useVersion } from "../../context/VersionContext"; // Import version context hook
import useFetch from "../../Hooks/useAxios";
import { useMessage } from "../../Hooks/MessageContext"; // Import message context hook
import { useAuth } from "../../context/AuthContext";

export default function Header() {
  const { user, role, logout } = useAuth();
  const displayName = user?.name || user || "";

  const { postData } = useFetch(); // Use the custom hook for API calls
  const { addMessage } = useMessage();

  const handleLogout = async () => {
    console.log("🔴 LOGOUT TRIGGERED: Header - Manual logout button clicked");
    try {
      await postData(APIs.LOGOUT);
      console.log("✅ Backend logout API call successful");
    } catch (error) {
      console.error("❌ Backend logout API call failed:", error);
      addMessage("Logout request failed, but clearing local session.", "error");
    } finally {
      // Clear any extra cookies not managed by auth
      Cookies.remove("email");
      Cookies.remove("jwt-token");
      Cookies.remove("refresh-token");
      // Clear session start timestamp (auto logout reference)
      try {
        localStorage.removeItem("login_timestamp");
        Cookies.remove("login_timestamp");
      } catch (_) {}
      logout("manual"); // Pass "manual" reason to avoid duplicate error messages
    }
  };
  const { mkDocsInternalPath } = useApiUrl(); // Get the dynamic base URL
  const { combinedVersion } = useVersion(); // Properly extract the combinedVersion from the hook

  const handleFaqclick = () => {
    window.open(mkDocs_baseURL + mkDocsInternalPath, "_blank");
  };

  return (
    <div className={styles.navbar}>
      <div className={styles.brand}>
        <img src={brandlogotwo} alt="Brandlogo" />
        <span className={styles.version_number} title={combinedVersion}>
          {combinedVersion}
        </span>
      </div>
      <div className={styles.menu}>
        <div className={styles.user_info}>
          <span className={styles.logged_in_user}>
            WELCOME <span className={styles.user_name}>{displayName === "Guest" ? displayName : `${displayName} (${role})`}</span>
          </span>
          <div className={styles.profile_icon}>
            <SVGIcons icon="fa-user" width={14} height={14} fill="#000" />
            <div className={styles.dropdown}>
              <button onClick={handleLogout} className={styles.dropdown_item}>
                Logout
              </button>
            </div>
          </div>
        </div>
        {/* <a href="http://10.208.85.72:9000/" target="_blank"> */}
        <div className={styles.faq_icon} onClick={handleFaqclick}>
          <SVGIcons icon="fa-question" width={14} height={14} />
        </div>
        {/* </a> */}
      </div>
    </div>
  );
}
