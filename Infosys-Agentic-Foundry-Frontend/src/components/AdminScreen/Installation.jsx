import { useState, useEffect, useRef } from "react";
import styles from "./Installation.module.css";
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import { useMessage } from "../../Hooks/MessageContext";
import Loader from "../commonComponents/Loader";
import Modal from "./commonComponents/Modal";

/**
 * Installation Component
 * Manages dependencies and server operations with tabbed interface
 * Tabs: Missing Modules | Installed Modules | Restart Server
 */
const Installation = () => {
  // Active tab state - 'missing' | 'installed' | 'restart'
  const [activeTab, setActiveTab] = useState("missing");
  
  // Loading and action states
  const [loading, setLoading] = useState(false);
  const [activeAction, setActiveAction] = useState("");
  
  // Missing modules state
  const [missingDependencies, setMissingDependencies] = useState([]);
  const [showMissingDependencies, setShowMissingDependencies] = useState(false);
  const [hasFetchedMissing, setHasFetchedMissing] = useState(false);
  const [missingSuccessMessage, setMissingSuccessMessage] = useState("");
  
  // Installed modules state
  const [installedModules, setInstalledModules] = useState([]);
  const [showInstalledModules, setShowInstalledModules] = useState(false);
  const [hasFetchedInstalled, setHasFetchedInstalled] = useState(false);
  const [installedSuccessMessage, setInstalledSuccessMessage] = useState("");
  
  // Restart server state
  const [restartResult, setRestartResult] = useState(null);
  const [isInstallationDone, setIsInstallationDone] = useState(false);
  
  // Install modal state
  const [showInstallModal, setShowInstallModal] = useState(false);
  const [packageInput, setPackageInput] = useState("");
  
  const { fetchData, postData } = useFetch();
  const { addMessage } = useMessage();
  
  // Track if the initial fetch has been triggered for each tab
  const missingFetchTriggered = useRef(false);
  const installedFetchTriggered = useRef(false);

  // Auto-fetch when "Missing Modules" tab is clicked
  useEffect(() => {
    if (activeTab === "missing" && !hasFetchedMissing && !missingFetchTriggered.current) {
      missingFetchTriggered.current = true;
      handleGetMissingDependencies();
    }
  }, [activeTab]);

  // Auto-fetch when "Installed Modules" tab is clicked
  useEffect(() => {
    if (activeTab === "installed" && !hasFetchedInstalled && !installedFetchTriggered.current) {
      installedFetchTriggered.current = true;
      handleGetInstalledModules();
    }
  }, [activeTab]);

  /**
   * Fetch missing dependencies from the server
   */
  const handleGetMissingDependencies = async () => {
    setLoading(true);
    setActiveAction("get-missing");
    setShowMissingDependencies(false);
    setMissingDependencies([]);
    setMissingSuccessMessage("");
    
    try {
      const response = await fetchData(APIs.GET_MISSING_DEPENDENCIES);
      console.log("Missing Dependencies API Response:", response);
      
      // Extract modules from response - handle different response formats
      let modules = [];
      if (Array.isArray(response)) {
        modules = response;
      } else if (response?.modules_to_install) {
        modules = response.modules_to_install;
      } else if (response?.modules) {
        modules = response.modules;
      } else if (response?.missing_dependencies) {
        modules = response.missing_dependencies;
      } else if (response?.data?.modules_to_install) {
        modules = response.data.modules_to_install;
      } else if (response?.data?.modules) {
        modules = response.data.modules;
      } else if (response?.data) {
        modules = Array.isArray(response.data) ? response.data : [];
      }
      
      setMissingDependencies(modules);
      setShowMissingDependencies(true);
      setHasFetchedMissing(true);
      
      // Show backend message if available
      if (response?.message) {
        if (modules.length === 0) {
          setMissingSuccessMessage(response.message);
        } else {
          addMessage(response.message, "info");
        }
      }
    } catch (error) {
      console.error("Missing Dependencies API Error:", error);
      addMessage(error?.response?.data?.detail || "Failed to fetch missing dependencies", "error");
    } finally {
      setLoading(false);
      setActiveAction("");
    }
  };

  /**
   * Fetch installed modules from the server
   */
  const handleGetInstalledModules = async () => {
    setLoading(true);
    setActiveAction("get-installed");
    setShowInstalledModules(false);
    setInstalledModules([]);
    setInstalledSuccessMessage("");
    
    try {
      // Using the same endpoint but parsing for installed modules
      // If there's a separate endpoint for installed modules, update this
      const response = await fetchData(APIs.GET_MISSING_DEPENDENCIES);
      console.log("Installed Modules API Response:", response);
      
      // Extract installed modules from response
      let modules = [];
      if (response?.installed_modules) {
        modules = response.installed_modules;
      } else if (response?.installed) {
        modules = response.installed;
      } else if (response?.data?.installed_modules) {
        modules = response.data.installed_modules;
      } else if (response?.data?.installed) {
        modules = response.data.installed;
      }
      
      setInstalledModules(modules);
      setShowInstalledModules(true);
      setHasFetchedInstalled(true);
      
      if (modules.length === 0) {
        setInstalledSuccessMessage("No installed modules information available");
      }
    } catch (error) {
      console.error("Installed Modules API Error:", error);
      addMessage(error?.response?.data?.detail || "Failed to fetch installed modules", "error");
    } finally {
      setLoading(false);
      setActiveAction("");
    }
  };

  /**
   * Open install dependencies modal
   */
  const openInstallModal = () => {
    setPackageInput("");
    setShowInstallModal(true);
  };

  /**
   * Close install dependencies modal
   */
  const closeInstallModal = () => {
    setShowInstallModal(false);
    setPackageInput("");
  };

  /**
   * Install dependencies from the modal input
   */
  const handleInstallDependencies = async () => {
    if (!packageInput.trim()) {
      addMessage("Please enter package name(s)", "error");
      return;
    }
    setLoading(true);
    setActiveAction("install");
    try {
      const modulesArray = packageInput
        .split(",")
        .map((m) => m.trim())
        .filter((m) => m.length > 0);
      
      const response = await postData(APIs.INSTALL_DEPENDENCIES, { modules: modulesArray });
      
      if (response?.is_install || response?.success === true) {
        setIsInstallationDone(true);
        addMessage(response?.message || "Dependencies installation started", "success");
        closeInstallModal();
        // Refresh missing dependencies after installation
        missingFetchTriggered.current = false;
        setHasFetchedMissing(false);
        if (activeTab === "missing") {
          handleGetMissingDependencies();
        }
      } else {
        const errorMsg = response?.detail || response?.message || "Installation failed";
        addMessage(errorMsg, "error");
      }
    } catch (error) {
      const errorMsg = error?.response?.data?.detail || error?.response?.data?.message || "Failed to install dependencies";
      addMessage(errorMsg, "error");
    } finally {
      setLoading(false);
      setActiveAction("");
    }
  };

  /**
   * Restart the server
   */
  const handleRestartServer = async () => {
    setLoading(true);
    setActiveAction("restart");
    setRestartResult(null);
    try {
      const response = await postData(APIs.RESTART_SERVER);
      
      if (response?.is_restart || response?.success === true) {
        setRestartResult({ type: "success", message: response?.message || "Server restart initiated successfully" });
        addMessage(response?.message || "Server restart initiated", "success");
      } else {
        const errorMsg = response?.detail || response?.message || "Failed to restart server";
        setRestartResult({ type: "error", message: errorMsg });
        addMessage(errorMsg, "error");
      }
    } catch (error) {
      const errorMsg = error?.response?.data?.detail || error?.response?.data?.message || "Failed to restart server";
      setRestartResult({ type: "error", message: errorMsg });
      addMessage(errorMsg, "error");
    } finally {
      setLoading(false);
      setActiveAction("");
    }
  };

  /**
   * Handle tab change
   */
  const handleTabChange = (tab) => {
    setActiveTab(tab);
  };

  /**
   * Refresh data for current tab
   */
  const handleRefresh = () => {
    if (activeTab === "missing") {
      missingFetchTriggered.current = false;
      setHasFetchedMissing(false);
      handleGetMissingDependencies();
    } else if (activeTab === "installed") {
      installedFetchTriggered.current = false;
      setHasFetchedInstalled(false);
      handleGetInstalledModules();
    }
  };

  /**
   * Render the Missing Modules tab content
   */
  const renderMissingModulesContent = () => (
    <div className={styles.tabContent}>
      <div className={styles.tabHeader}>
        <p className={styles.tabDescription}>
          View and install missing Python dependencies required by your tools and servers.
        </p>
        <div className={styles.tabActions}>
          <button 
            className="iafButton iafButtonSecondary" 
            onClick={handleRefresh} 
            disabled={loading}
            title="Refresh missing modules"
          >
            {activeAction === "get-missing" ? <><span className={styles.spinner}></span> Fetching...</> : "Refresh"}
          </button>
          <button 
            className="iafButton iafButtonPrimary" 
            onClick={openInstallModal} 
            disabled={loading}
          >
            Install Dependencies
          </button>
        </div>
      </div>
      
      {/* Display Missing Dependencies List */}
      {showMissingDependencies && missingDependencies.length > 0 && (
        <div className={styles.resultSection}>
          <div className={styles.packagesGrid}>
            {missingDependencies.map((dep, index) => {
              const packageName = typeof dep === "string" ? dep : dep?.name || JSON.stringify(dep);
              return (
                <div key={index} className={styles.packageCard} title={packageName}>
                  <span className={styles.packageName}>{packageName}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* No missing modules message */}
      {showMissingDependencies && missingDependencies.length === 0 && (
        <div className={styles.resultSection}>
          <div className={styles.emptyState}>
            <span className={styles.emptyIcon}>✓</span>
            <p className={styles.emptyMessage}>
              {missingSuccessMessage || "All dependencies are installed! No missing modules found."}
            </p>
          </div>
        </div>
      )}

      {/* Initial state - not yet fetched */}
      {!showMissingDependencies && !loading && (
        <div className={styles.resultSection}>
          <div className={styles.emptyState}>
            <span className={styles.emptyIcon}>📦</span>
            <p className={styles.emptyMessage}>Loading missing dependencies...</p>
          </div>
        </div>
      )}
    </div>
  );

  /**
   * Render the Installed Modules tab content
   */
  const renderInstalledModulesContent = () => (
    <div className={styles.tabContent}>
      <div className={styles.tabHeader}>
        <p className={styles.tabDescription}>
          View all currently installed Python modules in the environment.
        </p>
        <div className={styles.tabActions}>
          <button 
            className="iafButton iafButtonSecondary" 
            onClick={handleRefresh} 
            disabled={loading}
            title="Refresh installed modules"
          >
            {activeAction === "get-installed" ? <><span className={styles.spinner}></span> Fetching...</> : "Refresh"}
          </button>
        </div>
      </div>
      
      {/* Display Installed Modules List */}
      {showInstalledModules && installedModules.length > 0 && (
        <div className={styles.resultSection}>
          <div className={styles.packagesGrid}>
            {installedModules.map((mod, index) => {
              const moduleName = typeof mod === "string" ? mod : mod?.name || JSON.stringify(mod);
              const moduleVersion = typeof mod === "object" ? mod?.version : null;
              return (
                <div key={index} className={styles.packageCard} title={moduleVersion ? `${moduleName} (${moduleVersion})` : moduleName}>
                  <span className={styles.packageName}>{moduleName}</span>
                  {moduleVersion && <span className={styles.packageVersion}>{moduleVersion}</span>}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* No installed modules message */}
      {showInstalledModules && installedModules.length === 0 && (
        <div className={styles.resultSection}>
          <div className={styles.emptyState}>
            <span className={styles.emptyIcon}>📋</span>
            <p className={styles.emptyMessage}>
              {installedSuccessMessage || "No installed modules information available."}
            </p>
          </div>
        </div>
      )}

      {/* Initial state - not yet fetched */}
      {!showInstalledModules && !loading && (
        <div className={styles.resultSection}>
          <div className={styles.emptyState}>
            <span className={styles.emptyIcon}>📦</span>
            <p className={styles.emptyMessage}>Loading installed modules...</p>
          </div>
        </div>
      )}
    </div>
  );

  /**
   * Render the Restart Server tab content
   */
  const renderRestartServerContent = () => (
    <div className={styles.tabContent}>
      <div className={styles.tabHeader}>
        <p className={styles.tabDescription}>
          Restart the backend server to apply installed dependencies or configuration changes.
        </p>
      </div>
      
      <div className={styles.restartSection}>
        <div className={styles.restartCard}>
          <div className={styles.restartIcon}>🔄</div>
          <h3 className={styles.restartTitle}>Server Restart</h3>
          <p className={styles.restartDescription}>
            Clicking the button below will initiate a server restart. This may take a few moments.
            The server will be temporarily unavailable during the restart process.
          </p>
          <button 
            className="iafButton iafWarningButton" 
            onClick={handleRestartServer} 
            disabled={loading}
          >
            {activeAction === "restart" ? <><span className={styles.spinner}></span> Restarting...</> : "Restart Server"}
          </button>
        </div>

        {/* Restart Result */}
        {restartResult && (
          <div className={`${styles.restartResult} ${restartResult.type === "success" ? styles.restartSuccess : styles.restartError}`}>
            <span className={styles.restartResultIcon}>
              {restartResult.type === "success" ? "✓" : "✗"}
            </span>
            <p className={styles.restartResultMessage}>{restartResult.message}</p>
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className={styles.installationContainer}>
      {loading && <Loader contained />}

      {/* Sub-tabs Navigation */}
      <div className={styles.tabsContainer}>
        <button 
          className={`iafTabsBtn ${activeTab === "missing" ? "active" : ""}`}
          onClick={() => handleTabChange("missing")}
        >
          Missing Modules
        </button>
        <button 
          className={`iafTabsBtn ${activeTab === "installed" ? "active" : ""}`}
          onClick={() => handleTabChange("installed")}
        >
          Installed Modules
        </button>
        <button 
          className={`iafTabsBtn ${activeTab === "restart" ? "active" : ""}`}
          onClick={() => handleTabChange("restart")}
        >
          Restart Server
        </button>
      </div>

      {/* Tab Content */}
      {activeTab === "missing" && renderMissingModulesContent()}
      {activeTab === "installed" && renderInstalledModulesContent()}
      {activeTab === "restart" && renderRestartServerContent()}

      {/* Install Dependencies Modal */}
      <Modal
        isOpen={showInstallModal}
        onClose={closeInstallModal}
        title="Install Dependencies"
      >
        <div className={styles.modalBody}>
          <div className={styles.formGroup}>
            <label className={styles.inputLabel}>Package Name(s)</label>
            <input
              type="text"
              className={styles.inputField}
              placeholder="e.g., numpy, pandas, requests"
              value={packageInput}
              onChange={(e) => setPackageInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !loading && packageInput.trim() && handleInstallDependencies()}
              autoFocus
            />
            <span className={styles.inputHint}>Enter Python package names separated by commas</span>
          </div>
        </div>
        <div className={styles.modalFooter}>
          <button className="iafButton iafButtonSecondary" onClick={closeInstallModal}>
            Cancel
          </button>
          <button 
            className="iafButton iafButtonPrimary" 
            onClick={handleInstallDependencies}
            disabled={loading || !packageInput.trim()}
          >
            {activeAction === "install" ? <><span className={styles.spinner}></span> Installing...</> : "Install"}
          </button>
        </div>
      </Modal>
    </div>
  );
};

export default Installation;
