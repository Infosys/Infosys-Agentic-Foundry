import React from "react";
import styles from "../../css_modules/Header.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import brandlogotwo from "../../Assets/Agentic-Foundry-Logo-Blue-2.png";
import { useNavigate } from "react-router-dom";
import Cookies from "js-cookie";
import { mkDocs_baseURL } from "../../constant";
import { useApiUrl } from "../../context/ApiUrlContext"; // Import the hook
import { useVersion } from "../../context/VersionContext"; // Import version context hook

export default function Header() {
  const name = Cookies.get("userName");
  const role = Cookies.get("role");

  const [dropdownVisible, setDropdownVisible] = React.useState(false);

  const navigate = useNavigate();

  const handleLogout = () => {
    Cookies.remove("userName");
    Cookies.remove("session_id");
    Cookies.remove("csrf-token");
    Cookies.remove("email");
    Cookies.remove("role");
    setDropdownVisible(false);
    navigate("/login");
  };
  const { mkDocsInternalPath } = useApiUrl(); // Get the dynamic base URL
  const { combinedVersion } = useVersion(); // Properly extract the combinedVersion from the hook

  const toggleDropdown = () => {
    setDropdownVisible(!dropdownVisible);
  };

  const handleFaqclick = () => {
    window.open(mkDocs_baseURL+mkDocsInternalPath,'_blank');
  }

  return (
    <div className={styles.navbar}>
      <div className={styles.brand}>
        <img src={brandlogotwo} alt="Brandlogo" />
        <span className={styles.version_number} title={combinedVersion}>{combinedVersion}</span>
      </div>
      <div className={styles.menu}>
        <div className={styles.user_info}>
          <span className={styles.logged_in_user}>
            WELCOME <span className={styles.user_name}>
              {name === "Guest" ? name : `${name} (${role})`}
            </span>
          </span>
          <div className={styles.profile_icon} onClick={toggleDropdown}>
            <SVGIcons icon="fa-user" width={14} height={14} fill="#000" />
            {dropdownVisible && (
              <div className={styles.dropdown}>
                <button onClick={handleLogout} className={styles.dropdown_item}>
                  Logout
                </button>
              </div>
            )}
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
