import React from "react";
import SearchInputToolsAgents from "./SearchInputTools";
import SVGIcons from "../../Icons/SVGIcons";
import styles from "./SubHeader.module.css";
import Cookies from "js-cookie";
import DeleteModal from "./DeleteModal";
import { faRefresh } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { useAuth } from "../../context/AuthContext";

const SubHeader = (props) => {
  const {
    onSearch,
    onSettingClick,
    onPlusClick,
    selectedTags,
    heading,
    activeTab,
    handleRefresh,
    clearSearch,
    showAgentTypeDropdown = false,
    agentTypes = [],
    selectedAgentType = "",
    handleAgentTypeChange = () => {},
  } = props;

  // Determine placeholder based on the heading prop and activeTab
  const getSearchPlaceholder = () => {
    if (heading === "AGENTS") return "Search Agents";
    if (heading === "SERVERS" || activeTab === "servers") return "Search Servers";
    if (heading === "TOOLS" || activeTab === "tools") return "Search Tools";
    if (heading === "") {
      // For tools context
      return "Search Tools";
    }
    return "Search";
  };

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
    if (typeof onPlusClick === "function") {
      onPlusClick();
      return;
    }
    try {
      window.dispatchEvent(new CustomEvent("openToolOnboard"));
    } catch (e) {}
  };

  const { logout } = useAuth();

  const handleLoginButton = (e) => {
    e.preventDefault();
    logout("/login");
  };

  return (
    <>
      <DeleteModal show={showAddModal} onClose={() => setShowAddModal(false)}>
        <p>You are not authorized to add/modify. Please login with registered email.</p>
        {handleRefresh && (
          <div className={styles.buttonContainer}>
            <button onClick={(e) => handleLoginButton(e)} className={styles.loginBtn}>Login</button>
            <button onClick={() => setShowAddModal(false)} className={styles.cancelBtn}>Cancel</button>
          </div>
        )}
      </DeleteModal>
      <div className={styles.container}>
        <div className={styles.titleContainer}>
          <h6>{heading}</h6>
          <button
            type="button"
            onClick={() => {
              if (typeof handleRefresh === "function") handleRefresh();
            }}
            title={"Refresh"}
            className={styles.refreshButton}>
            <FontAwesomeIcon icon={faRefresh} />
          </button>
        </div>

        <div className={styles.rightPart}>
          {showAgentTypeDropdown && (
            <div className={styles.dropdownContainer}>
              <select id="agentTypeDropdown" className={styles.agentTypeDropdown} value={selectedAgentType} onChange={handleAgentTypeChange}>
                <option value="">All</option>
                {agentTypes.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </select>
            </div>
          )}
          <SearchInputToolsAgents inputProps={{ placeholder: getSearchPlaceholder() }} handleSearch={handleSearch} heading={heading} clearSearch={clearSearch} searchValue={props.searchValue} />
          <button type="button" onClick={handleSettingClick} className={styles.setting}>
            {selectedTags?.length > 0 && <span className={styles.badge}>{selectedTags?.length}</span>}
            <SVGIcons icon="slider-rect" width={20} height={18} fill="#C3C1CF" />
          </button>
          <button type="button" onClick={handlePlusClick} className={styles.plus}>
            <SVGIcons icon="fa-plus" fill="#007CC3" width={16} height={16} />
          </button>
        </div>
      </div>
    </>
  );
};

export default SubHeader;
