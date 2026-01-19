import { useState, useEffect, useRef } from "react";
import styles from "./Installation.module.css";
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import { useMessage } from "../../Hooks/MessageContext";
import Loader from "../commonComponents/Loader";


const InstalledModules = () => {
  const [loading, setLoading] = useState(true);
  const [installedPackages, setInstalledPackages] = useState([]);
  const [showPackages, setShowPackages] = useState(false);
  const [hasFetched, setHasFetched] = useState(false);
  const [successMessage, setSuccessMessage] = useState("");
  const [searchTerm, setSearchTerm] = useState("");

  const { fetchData } = useFetch();
  const { addMessage } = useMessage();

  // Track if the initial fetch has been triggered
  const fetchTriggered = useRef(false);

  // Auto-fetch on mount
  useEffect(() => {
    if (!hasFetched && !fetchTriggered.current) {
      fetchTriggered.current = true;
      handleGetInstalledPackages();
    }
  }, []);

  /**
   * Fetch installed packages from the server
   */
  const handleGetInstalledPackages = async () => {
    setLoading(true);
    setShowPackages(false);
    setInstalledPackages([]);
    setSuccessMessage("");

    try {
      const response = await fetchData(APIs.GET_INSTALLED_PACKAGES);

      // Extract packages from response - handle different response formats
      let packages = [];
      if (Array.isArray(response)) {
        packages = response;
      } else if (response?.packages) {
        packages = response.packages;
      } else if (response?.installed_packages) {
        packages = response.installed_packages;
      } else if (response?.modules) {
        packages = response.modules;
      } else if (response?.data?.packages) {
        packages = response.data.packages;
      } else if (response?.data?.installed_packages) {
        packages = response.data.installed_packages;
      } else if (response?.data) {
        packages = Array.isArray(response.data) ? response.data : [];
      }

      setInstalledPackages(packages);
      setShowPackages(true);
      setHasFetched(true);

      // Show backend message if available
      if (response?.message && packages.length === 0) {
        setSuccessMessage(response.message);
      }
    } catch (error) {
      addMessage(error?.response?.data?.message || error?.response?.data?.detail, "error");
    } finally {
      setLoading(false);
    }
  };

  /**
   * Get package name from package object
   */
  const getPackageName = (pkg) => {
    return typeof pkg === "string" ? pkg : pkg?.name || JSON.stringify(pkg);
  };

  /**
   * Filter packages based on search term
   */
  const filteredPackages = installedPackages.filter((pkg) => {
    const packageName = getPackageName(pkg).toLowerCase();
    return packageName.includes(searchTerm.toLowerCase());
  });

  return (
    <div className={styles.pageWrapper}>
      {loading && (
        <div className={styles.loaderOverlay}>
          <Loader contained />
        </div>
      )}
      <h6 className={styles.pageHeading}>INSTALLED MODULES</h6>
      <div className={styles.installationContainer}>

        <div className={styles.tabContent}>
        {/* Search Input */}
        {showPackages && installedPackages.length > 0 && (
          <div className={styles.searchWrapper}>
            <div className={styles.searchContainer}>
              <input
                type="text"
                className={styles.searchInput}
                placeholder="Search packages..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
              <button className={styles.searchButton} type="button">
                <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" fill="none" />
                  <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </button>
            </div>
          </div>
        )}

        {/* Display Installed Packages List */}
        {showPackages && filteredPackages.length > 0 && (
          <div className={styles.resultSection}>
            <div className={styles.packagesGrid}>
              {filteredPackages.map((pkg, index) => {
                const packageName = getPackageName(pkg);
                return (
                  <div key={index} className={styles.packageCard} title={packageName}>
                    <span className={styles.packageName}>{packageName}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* No results from search */}
        {showPackages && installedPackages.length > 0 && filteredPackages.length === 0 && (
          <div className={styles.resultSection}>
            <div className={styles.emptyState}>
              <span className={styles.emptyIcon}>🔍</span>
              <p className={styles.emptyMessage}>No packages found matching "{searchTerm}"</p>
            </div>
          </div>
        )}

        {/* No installed packages message */}
        {showPackages && installedPackages.length === 0 && (
          <div className={styles.resultSection}>
            <div className={styles.emptyState}>
              <span className={styles.emptyIcon}>📦</span>
              <p className={styles.emptyMessage}>{successMessage || "No installed packages found."}</p>
            </div>
          </div>
        )}
        </div>
      </div>
    </div>
  );
};

export default InstalledModules;
