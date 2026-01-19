import { useState, useEffect, useRef } from "react";
import styles from "./Installation.module.css";
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import { useMessage } from "../../Hooks/MessageContext";
import Loader from "../commonComponents/Loader";

/**
 * MissingModules Component
 * Displays missing Python dependencies with selection, version input, and install functionality
 * Auto-fetches missing modules on mount
 */
const MissingModules = () => {
  const [loading, setLoading] = useState(true);
  const [installing, setInstalling] = useState(false);
  const [missingDependencies, setMissingDependencies] = useState([]);
  const [showMissingDependencies, setShowMissingDependencies] = useState(false);
  const [hasFetchedMissing, setHasFetchedMissing] = useState(false);
  const [missingSuccessMessage, setMissingSuccessMessage] = useState("");
  // Store selected modules with their versions: { moduleName: version }
  const [selectedModules, setSelectedModules] = useState({});
  // Modal state for adding new module
  const [showAddModal, setShowAddModal] = useState(false);
  const [newModuleName, setNewModuleName] = useState("");
  const [newModuleVersion, setNewModuleVersion] = useState("");
  const [installingNewModule, setInstallingNewModule] = useState(false);
  // Restart server state
  const [restarting, setRestarting] = useState(false);

  const { fetchData, postData } = useFetch();
  const { addMessage } = useMessage();

  // Track if the initial fetch has been triggered
  const fetchTriggered = useRef(false);

  // Auto-fetch on mount
  useEffect(() => {
    if (!hasFetchedMissing && !fetchTriggered.current) {
      fetchTriggered.current = true;
      handleGetMissingDependencies();
    }
  }, []);

  /**
   * Fetch missing dependencies from the server
   */
  const handleGetMissingDependencies = async () => {
    setLoading(true);
    setShowMissingDependencies(false);
    setMissingDependencies([]);
    setMissingSuccessMessage("");
    setSelectedModules({});

    try {
      const response = await fetchData(APIs.GET_MISSING_DEPENDENCIES);

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
      if (response?.message && modules.length === 0) {
        setMissingSuccessMessage(response.message);
      }
    } catch (error) {
      addMessage(error?.response?.data?.message || error?.response?.data?.detail, "error");
    } finally {
      setLoading(false);
    }
  };

  /**
   * Get package name from dependency object
   */
  const getPackageName = (dep) => {
    return typeof dep === "string" ? dep : dep?.name || JSON.stringify(dep);
  };

  /**
   * Toggle selection of a single module
   */
  const handleToggleSelect = (dep) => {
    const packageName = getPackageName(dep);
    setSelectedModules((prev) => {
      if (packageName in prev) {
        // Remove from selection
        const { [packageName]: removed, ...rest } = prev;
        return rest;
      } else {
        // Add to selection with empty version (latest)
        return { ...prev, [packageName]: "" };
      }
    });
  };

  /**
   * Update version for a selected module
   */
  const handleVersionChange = (packageName, version) => {
    setSelectedModules((prev) => ({
      ...prev,
      [packageName]: version,
    }));
  };

  /**
   * Toggle select all modules
   */
  const handleSelectAll = () => {
    const selectedCount = Object.keys(selectedModules).length;
    if (selectedCount === missingDependencies.length) {
      // Deselect all
      setSelectedModules({});
    } else {
      // Select all with empty versions
      const allSelected = {};
      missingDependencies.forEach((dep) => {
        const name = getPackageName(dep);
        allSelected[name] = selectedModules[name] || "";
      });
      setSelectedModules(allSelected);
    }
  };

  /**
   * Install selected dependencies
   */
  const handleInstallDependencies = async () => {
    const selectedCount = Object.keys(selectedModules).length;
    if (selectedCount === 0) {
      addMessage("Please select at least one module to install", "error");
      return;
    }

    setInstalling(true);
    try {
      // Build modules array with versions (e.g., "numpy==1.24.0" or just "numpy" for latest)
      const modulesWithVersions = Object.entries(selectedModules).map(([name, version]) => {
        return version ? `${name}==${version}` : name;
      });

      const response = await postData(APIs.INSTALL_DEPENDENCIES, { modules: modulesWithVersions });

      if (response?.is_install || response?.success === true) {
        addMessage(response?.message, "success");
        // Refresh the list after installation
        fetchTriggered.current = false;
        setHasFetchedMissing(false);
        handleGetMissingDependencies();
      } else {
        addMessage(response?.message || response?.detail, "error");
      }
    } catch (error) {
      addMessage(error?.response?.data?.message || error?.response?.data?.detail, "error");
    } finally {
      setInstalling(false);
    }
  };

  /**
   * Install a new module from the modal
   */
  const handleInstallNewModule = async () => {
    if (!newModuleName.trim()) {
      addMessage("Please enter a module name", "error");
      return;
    }

    setInstallingNewModule(true);
    try {
      const moduleToInstall = newModuleVersion.trim()
        ? `${newModuleName.trim()}==${newModuleVersion.trim()}`
        : newModuleName.trim();

      const response = await postData(APIs.INSTALL_DEPENDENCIES, { modules: [moduleToInstall] });

      if (response?.is_install || response?.success === true) {
        addMessage(response?.message, "success");
        setShowAddModal(false);
        setNewModuleName("");
        setNewModuleVersion("");
        // Refresh the list after installation
        fetchTriggered.current = false;
        setHasFetchedMissing(false);
        handleGetMissingDependencies();
      } else {
        addMessage(response?.message || response?.detail, "error");
      }
    } catch (error) {
      addMessage(error?.response?.data?.message || error?.response?.data?.detail, "error");
    } finally {
      setInstallingNewModule(false);
    }
  };

  /**
   * Close modal and reset form
   */
  const handleCloseModal = () => {
    setShowAddModal(false);
    setNewModuleName("");
    setNewModuleVersion("");
  };

  /**
   * Restart the server
   */
  const handleRestartServer = async () => {
    setRestarting(true);
    try {
      const response = await postData(APIs.RESTART_SERVER);

      if (response?.is_restart || response?.success === true) {
        addMessage(response?.message, "success");
      } else {
        addMessage(response?.detail || response?.message, "error");
      }
    } catch (error) {
      addMessage(error?.response?.data?.message || error?.response?.data?.detail, "error");
    } finally {
      setRestarting(false);
    }
  };

  const selectedCount = Object.keys(selectedModules).length;
  const isAllSelected = missingDependencies.length > 0 && selectedCount === missingDependencies.length;
  const hasSelection = selectedCount > 0;

  return (
    <div className={styles.pageWrapper}>
      {(loading || installing || installingNewModule || restarting) && (
        <div className={styles.loaderOverlay}>
          <Loader contained />
        </div>
      )}
      <h6 className={styles.pageHeading}>MISSING MODULES</h6>
      <div className={styles.installationContainer}>

        <div className={styles.tabContent}>
        {/* Header with Select All, Install button and Add button */}
        <div className={styles.modulesHeader}>
          {/* {showMissingDependencies && missingDependencies.length > 0 ? (
            <label className={styles.selectAllLabel}>
              <input
                type="checkbox"
                checked={isAllSelected}
                onChange={handleSelectAll}
                className={styles.checkbox}
              />
              <span>Select All ({selectedCount}/{missingDependencies.length})</span>
            </label>
          ) : (
            <div></div>
          )} */}
          <div className={styles.headerActions}>
            {/* <button
              className="iafButton iafButtonPrimary"
              onClick={handleRestartServer}
              disabled
              title="Restart Server"
            >
              {restarting ? "Restarting..." : "Restart Server"}
            </button> */}
            {/* {showMissingDependencies && missingDependencies.length > 0 && (
              <button
                className="iafButton iafButtonPrimary"
                onClick={handleInstallDependencies}
                disabled={!hasSelection || installing}
              >
                {installing ? (
                  <>
                    <span className={styles.spinner}></span> Installing...
                  </>
                ) : (
                  `Install`
                )}
              </button>
            )} */}
            {/* <button
              type="button"
              className={styles.addButton}
              onClick={() => setShowAddModal(true)}
              title="Add New Module"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 5v14M5 12h14" stroke="#007CC3" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button> */}
          </div>
        </div>

        {/* Display Missing Dependencies List */}
        {showMissingDependencies && missingDependencies.length > 0 && (
          <div className={styles.resultSection}>
            <div className={styles.packagesGrid}>
              {missingDependencies.map((dep, index) => {
                const packageName = getPackageName(dep);
                const isSelected = packageName in selectedModules;
                return (
                  <div
                    key={index}
                    className={`${styles.packageCard} ${isSelected ? styles.packageCardSelected : ""}`}
                    title={packageName}
                  >
                    <div className={styles.cardHeader} onClick={() => handleToggleSelect(dep)}>
                      {/* <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => handleToggleSelect(dep)}
                        className={styles.cardCheckbox}
                        onClick={(e) => e.stopPropagation()}
                      /> */}
                      <span className={styles.packageName}>{packageName}</span>
                    </div>
                    {/* {isSelected && (
                      <input
                        type="text"
                        className={styles.versionInput}
                        placeholder="Version (e.g., 1.24.0)"
                        value={selectedModules[packageName] || ""}
                        onChange={(e) => handleVersionChange(packageName, e.target.value)}
                        onClick={(e) => e.stopPropagation()}
                      />
                    )} */}
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
              <p className={styles.emptyMessage}>{missingSuccessMessage || "All dependencies are installed! No missing modules found."}</p>
            </div>
          </div>
        )}
      </div>

      {/* Add Module Modal */}
      {showAddModal && (
        <div className={styles.modalOverlay} onClick={handleCloseModal}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h4>Install New Module</h4>
              <button className={styles.closeBtn} onClick={handleCloseModal} type="button">
                ×
              </button>
            </div>
            <div className={styles.modalContent}>
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Module Name <span className={styles.required}>*</span></label>
                <input
                  type="text"
                  className={styles.formInput}
                  placeholder="e.g., numpy, pandas, requests"
                  value={newModuleName}
                  onChange={(e) => setNewModuleName(e.target.value)}
                  autoFocus
                />
              </div>
              
              <div className={styles.modalActions}>
                <button
                  className="iafButton iafButtonSecondary"
                  onClick={handleCloseModal}
                  type="button"
                >
                  Cancel
                </button>
                <button
                  className="iafButton iafButtonPrimary"
                  onClick={handleInstallNewModule}
                  disabled={!newModuleName.trim() || installingNewModule}
                  type="button"
                >
                  {installingNewModule ? "Installing..." : "Install"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  );
};

export default MissingModules;
