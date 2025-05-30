import React from "react";
import SearchInputToolsAgents from "./SearchInputTools";
import SVGIcons from "../../Icons/SVGIcons";
import styles from "./SubHeader.module.css";
import Cookies from "js-cookie";
import DeleteModal from "./DeleteModal";
import { useNavigate } from "react-router-dom";
import { faRefresh } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";

const SubHeader = (props) => {
  const {
    onSearch,
    onSettingClick,
    onPlusClick,
    selectedTags,
    heading,
    handleRefresh,
    clearSearch,
  } = props;

  const userName = Cookies.get("userName");

  const [showAddModal, setShowAddModal] = React.useState(false);

  const handleSearch = (searchValue) => {
    onSearch(searchValue);
  };
  const handleSettingClick = () => {
    onSettingClick();
  };
  const handlePlusClick = () => {
    if (userName === "Guest") {
      setShowAddModal(true);
      return;
    }
    onPlusClick();
  };

  const navigate = useNavigate();

  const handleLoginButton = (e) => {
    e.preventDefault();
    Cookies.remove("userName");
    Cookies.remove("session_id");
    Cookies.remove("csrf-token");
    Cookies.remove("email");
    Cookies.remove("role");
    navigate("/login");
  };

  return (
    <>
      <DeleteModal show={showAddModal} onClose={() => setShowAddModal(false)}>
        <p>
          You are not authorized to add an agent. Please login with registered
          email.
        </p>
        {handleRefresh && (
          <button onClick={(e) => handleLoginButton(e)}>Login</button>
        )}
      </DeleteModal>
      <div className={styles.container}>
        <div className={styles.titleContainer}>
          <h6>{heading}</h6>
          <button
            onClick={handleRefresh}
            title={"Refresh"}
            className={styles.refreshButton}
          >
            <FontAwesomeIcon icon={faRefresh} />
          </button>
        </div>

        <div className={styles.rightPart}>
          <SearchInputToolsAgents
            inputProps={{ placeholder: "SEARCH" }}
            handleSearch={handleSearch}
            heading={heading}
            clearSearch={clearSearch}
          />
          <button onClick={handleSettingClick} className={styles.setting}>
            {selectedTags?.length > 0 && (
              <span className={styles.badge}>{selectedTags?.length}</span>
            )}
            <SVGIcons
              icon="slider-rect"
              width={20}
              height={18}
              fill="#C3C1CF"
            />
          </button>
          <button onClick={handlePlusClick} className={styles.plus}>
            <SVGIcons icon="fa-plus" fill="#007CC3" width={16} height={16} />
          </button>
        </div>
      </div>
    </>
  );
};

export default SubHeader;