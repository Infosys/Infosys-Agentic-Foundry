import React from "react";
import styles from "../../css_modules/Header.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import brandlogotwo from "../../Assets/brandlogo.png";
import { useNavigate } from "react-router-dom";
import Cookies from "js-cookie";

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

  const toggleDropdown = () => {
    setDropdownVisible(!dropdownVisible);
  };

  return (
    <div className={styles.navbar}>
      <div className={styles.brand}>
        <img src={brandlogotwo} alt="Brandlogo" />
      </div>
      <div className={styles.menu}>
        <div className={styles.user_info}>
          <span className={styles.logged_in_user}>
            WELCOME <span className={styles.user_name}>
              {name === "Guest" ? name : `${name} (${role})`}
            </span>
          </span>
          <div className={styles.profile_icon} onClick={toggleDropdown}>
            <SVGIcons icon="fa-user" width={18} height={18} fill="#000" />
            {dropdownVisible && (
              <div className={styles.dropdown}>
                <button onClick={handleLogout} className={styles.dropdown_item}>
                  Logout
                </button>
              </div>
            )}
          </div>
        </div>
        <a href="#">
          <div className={styles.faq_icon}>
            <SVGIcons icon="fa-question" width={18} height={18} />
          </div>
        </a>
      </div>
    </div>
  );
}
