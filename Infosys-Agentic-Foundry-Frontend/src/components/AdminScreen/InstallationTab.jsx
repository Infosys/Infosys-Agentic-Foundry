import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom";
import { useMessage } from "../../Hooks/MessageContext";
import styles from "./InstallationTab.module.css";
import { useInstallationService } from "../../services/installationService";
import Loader from "../commonComponents/Loader";
import DisplayCard1 from "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1.jsx";
import CodeEditor from "../commonComponents/CodeEditor.jsx";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine.jsx";
import EmptyState from "../commonComponents/EmptyState.jsx";

const InstallationTab = ({
  searchValue = "",
  type = "installed",
  externalShowModal = false,
  onExternalModalClose,
  onSelectionChange, // Callback to parent with selected count
  onInstallReady, // Callback to parent with install handler
  onClearSearch, // Callback to clear search from parent
}) => {
  const [installed, setInstalled] = useState([]);
  const [loading, setLoading] = useState(false);
  // const [selected, setSelected] = useState([]);
  // const [versions, setVersions] = useState({});
  // const [showModal, setShowModal] = useState(false);
  // const [customModule, setCustomModule] = useState("");
  // For pending modules details
  const [pendingDetails, setPendingDetails] = useState([]);
  const [selectedPendingModule, setSelectedPendingModule] = useState(null);
  // const restartServer = ...
  // const installDependencies = ...
  const { getInstalledPackages, getMissingDependencies, getPendingModules } = useInstallationService();
  // eslint-disable-next-line no-unused-vars
  const { addMessage } = useMessage();

  // useEffect(() => {
  //   if (externalShowModal) {
  //     setShowModal(true);
  //   }
  // }, [externalShowModal]);

  // const handleModalClose = () => {
  //   setShowModal(false);
  //   setCustomModule("");
  //   if (onExternalModalClose) {
  //     onExternalModalClose();
  //   }
  // };

  // Helper to get fetch function based on type
  const getFetchFunction = () => {
    if (type === "missing") return getMissingDependencies;
    if (type === "pending") return getPendingModules;
    return getInstalledPackages;
  };

  useEffect(() => {
    let didCancel = false;
    setLoading(true);
    const fetchFn = getFetchFunction();
    fetchFn()
      .then((res) => {
        let arr = [];
        if (res && typeof res === "object") {
          let pkgString;
          if (type === "missing") {
            pkgString = res.modules_to_install || [];
          } else if (type === "pending") {
            // Handle pending modules response - store both modules list and details
            pkgString = res.modules || [];
            if (res.details && Array.isArray(res.details)) {
              setPendingDetails(res.details);
            }
          } else {
            pkgString = res.packages || res.data || res.result || res.installed || "";
          }
          if (typeof pkgString === "string") {
            if (pkgString.includes(",")) {
              arr = pkgString
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean);
            } else {
              arr = pkgString.split(/\r?\n/).filter(Boolean);
            }
          } else if (Array.isArray(pkgString)) {
            arr = pkgString;
          }
          if (arr.length === 0 && type !== "missing" && type !== "pending") {
            for (const val of Object.values(res)) {
              if (typeof val === "string" && val.includes("==")) {
                if (val.includes(",")) {
                  arr = val
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean);
                } else {
                  arr = val.split(/\r?\n/).filter(Boolean);
                }
                break;
              }
            }
          }
        }
        if (arr.length === 0 && typeof res === "string") {
          arr = res.split(/\r?\n/).filter(Boolean);
        } else if (arr.length === 0 && Array.isArray(res)) {
          arr = res;
        }
        // Debug log
        if (type === "missing" || type === "pending") {
          // eslint-disable-next-line no-console
          console.log(`[DEBUG] ${type} modules API response:`, res, "parsed:", arr);
        }
        if (!didCancel) setInstalled(arr);
        // if (type === "missing") {
        //   setSelected([]);
        //   setVersions({});
        // }
      })
      .catch(() => {
        if (!didCancel) setInstalled([]);
      })
      .finally(() => {
        if (!didCancel) setLoading(false);
      });
    return () => {
      didCancel = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type]);

  // Filtered packages
  const filtered = installed.filter((pkg) => pkg.toLowerCase().includes(searchValue.toLowerCase()));

  // const installHandlerRef = useRef(null);

  // const handleInstall = useCallback(async () => {
  //   if (selected.length === 0) return;
  //   try {
  //     await installDependencies(selected);
  //     addMessage("Modules installation request sent successfully!", "success");
  //     // Refresh the missing modules list
  //     setLoading(true);
  //     const res = await getMissingDependencies();
  //     let arr = [];
  //     if (res && typeof res === "object") {
  //       const pkgString = res.modules_to_install || [];
  //       if (typeof pkgString === "string") {
  //         if (pkgString.includes(",")) {
  //           arr = pkgString
  //             .split(",")
  //             .map((s) => s.trim())
  //             .filter(Boolean);
  //         } else {
  //           arr = pkgString.split(/\r?\n/).filter(Boolean);
  //         }
  //       } else if (Array.isArray(pkgString)) {
  //         arr = pkgString;
  //       }
  //     }
  //     if (arr.length === 0 && typeof res === "string") {
  //       arr = res.split(/\r?\n/).filter(Boolean);
  //     } else if (arr.length === 0 && Array.isArray(res)) {
  //       arr = res;
  //     }
  //     setInstalled(arr);
  //     setSelected([]);
  //     setVersions({});
  //     if (onSelectionChange) {
  //       onSelectionChange(0);
  //     }
  //     setLoading(false);
  //   } catch (e) {
  //     addMessage("Failed to install modules.", "error");
  //   }
  // }, [selected, installDependencies, getMissingDependencies, addMessage, onSelectionChange]);

  // installHandlerRef.current = handleInstall;

  // useEffect(() => {
  //   if (type === "missing" && onInstallReady) {
  //     // Pass a wrapper that always calls the latest handler via ref
  //     onInstallReady(() => installHandlerRef.current?.());
  //   }
  // }, [type, onInstallReady]);

  // --- MISSING MODULES UI ---
  if (type === "missing") {
    // COMMENTED OUT: Select All functionality
    // const allSelected = filtered.length > 0 && filtered.every((pkg) => selected.includes(pkg));

    // COMMENTED OUT: Select All functionality
    // const handleSelectAll = () => {
    //   const newSelected = allSelected ? [] : filtered;
    //   setSelected(newSelected);
    //   if (onSelectionChange) {
    //     onSelectionChange(newSelected.length);
    //   }
    // };

    // COMMENTED OUT: Individual module selection
    // const handleSelect = (pkg) => {
    //   setSelected((sel) => {
    //     const newSelected = sel.includes(pkg) ? sel.filter((p) => p !== pkg) : [...sel, pkg];
    //     if (onSelectionChange) {
    //       onSelectionChange(newSelected.length);
    //     }
    //     return newSelected;
    //   });
    // };

    // COMMENTED OUT: Version change functionality
    // const handleVersionChange = (pkg, val) => {
    //   setVersions((v) => ({ ...v, [pkg]: val }));
    // };

    // COMMENTED OUT: Restart Server functionality
    // const handleRestartServer = async () => {
    //   try {
    //     await restartServer();
    //     addMessage("Server restart request sent successfully!", "success");
    //   } catch (e) {
    //     addMessage("Failed to restart server.", "error");
    //   }
    // };

    // Transform missing packages for DisplayCard1 - same pattern as installed
    const transformedMissing = filtered.map((pkg) => {
      const [moduleName, version] = pkg.split("==");
      return {
        module_name: moduleName || pkg,
        version: version ? `Version: ${version}` : "",
        category: "uncategorized", // Hides footer
      };
    });

    return (
      <>
        <SummaryLine visibleCount={filtered.length} totalCount={installed.length} />
        <div className="listWrapper">
          {loading ? (
            <Loader />
          ) : filtered.length > 0 ? (
            <DisplayCard1
              data={transformedMissing}
              cardNameKey="module_name"
              cardDescriptionKey="version"
              cardOwnerKey=""
              cardCategoryKey="category"
              emptyMessage="No missing modules found."
              loading={loading}
              showCreateCard={false}
              showButton={false}
              showCheckbox={false}
              showDeleteButton={false}
              footerButtonsConfig={[]}
              className="missingModulesCards"
            />
          ) : searchValue.trim() ? (
            <EmptyState filters={[`Search: ${searchValue}`]} onClearFilters={onClearSearch} message="No missing modules found" showCreateButton={false} />
          ) : (
            <EmptyState message="No missing modules found" subMessage="All required dependencies are installed" showClearFilter={false} showCreateButton={false} />
          )}
        </div>
        {/*
        <div className={styles.cardsGrid}>
          {filtered.map((pkg, idx) => {
            const isChecked = selected.includes(pkg);
            return (
              <div key={pkg} className={styles.card}>
                <div className={styles.cardCheckboxRow}>
                  {/* COMMENTED OUT: Checkbox for module selection */}
        {/* <input type="checkbox" checked={isChecked} onChange={() => handleSelect(pkg)} className={styles.cardCheckbox} /> */}
        {/* <span className={styles.cardModuleName}>{pkg}</span>
                </div>
                {/* COMMENTED OUT: Version input field */}
        {/* {isChecked && (
                  <input
                    type="text"
                    placeholder="Version (e.g., 1.24.0)"
                    value={versions[pkg] || ""}
                    onChange={(e) => handleVersionChange(pkg, e.target.value)}
                    className={styles.versionInput}
                  />
                )} */}
        {/* </div>
            );
          })}
        </div>
        */}
        {/*
        {showModal && (
          <div className={styles.customModalOverlay}>
            <div className={styles.customModalContent}>
              <button onClick={handleModalClose} className={styles.customModalCloseBtn}>
                ×
              </button>
              <h2 className={styles.customModalTitle}>Install New Module</h2>
              <div className={styles.customModalInputGroup}>
                <label className="label-desc">
                  Module Name <span className={styles.requiredAsterisk}>*</span>
                </label>
                <input
                  type="text"
                  placeholder="e.g., numpy, pandas, requests"
                  value={customModule}
                  onChange={(e) => setCustomModule(e.target.value)}
                  className={styles.customModalInput}
                />
              </div>
              <div className={styles.customModalActions}>
                <button onClick={handleModalClose} className={styles.cancelBtn}>
                  Cancel
                </button>
                <button disabled={!customModule.trim()} className={styles.customInstallBtn}>
                  Install
                </button>
              </div>
            </div>
          </div>
        )}
        */}
      </>
    );
  }

  // --- PENDING MODULES UI ---
  if (type === "pending") {
    // Transform pending modules (simple list of names) for DisplayCard1
    const transformedPending = filtered.map((moduleName) => ({
      module_name: moduleName,
      category: "uncategorized", // Hides footer
    }));

    // Filter pending details based on search for modal
    const getModuleDetails = (moduleName) => {
      return pendingDetails.find((detail) => detail.module_name === moduleName);
    };

    // Format date for display
    const formatDate = (dateString) => {
      if (!dateString) return "--";
      const date = new Date(dateString);
      return date.toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    };

    // Handle card click to show details modal
    const handlePendingCardClick = (cardName, item) => {
      const details = getModuleDetails(item.module_name);
      if (details) {
        setSelectedPendingModule(details);
      } else {
        // If no details, create a basic object with just the name
        setSelectedPendingModule({ module_name: item.module_name });
      }
    };

    return (
      <>
        <SummaryLine visibleCount={filtered.length} totalCount={installed.length} />
        <div className="listWrapper">
          {loading ? (
            <Loader />
          ) : filtered.length > 0 ? (
            <DisplayCard1
              data={transformedPending}
              cardNameKey="module_name"
              cardDescriptionKey=""
              cardOwnerKey=""
              cardCategoryKey="category"
              emptyMessage="No pending modules found."
              loading={loading}
              onCardClick={handlePendingCardClick}
              showCreateCard={false}
              showButton={false}
              showCheckbox={false}
              showDeleteButton={false}
              footerButtonsConfig={[]}
              className="pendingModulesCards"
            />
          ) : (
            <EmptyState
              filters={searchValue ? [`Search: ${searchValue}`] : []}
              onClearFilters={onClearSearch}
              message={searchValue ? "No pending modules found" : "No pending modules found"}
              subMessage={searchValue ? "" : "There are no modules pending installation"}
              showClearFilter={Boolean(searchValue)}
              showCreateButton={false}
            />
          )}
        </div>

        {/* Detail Modal for Pending Module - matches AvailableServers modal design */}
        {selectedPendingModule && ReactDOM.createPortal(
          <div className={`${styles.modalOverlay} ${type}`} onClick={() => setSelectedPendingModule(null)}>
            <div className={`${styles.modal} ${styles.modalWide}`} onClick={(e) => e.stopPropagation()}>
              <button className={`closeBtn ${styles.closeBtn}`} onClick={() => setSelectedPendingModule(null)}>
                ×
              </button>
              <h3 className={styles.modalTitle}>{selectedPendingModule.module_name}</h3>
              <div className={styles.modalBody}>
                {/* Left side - Info */}
                <div className={styles.modalLeft}>
                  <div className={styles.infoGrid}>
                    <div className={styles.infoCol}>
                      <div className={styles.infoRow}>
                        <strong>Tool Name:</strong>
                        <span>{selectedPendingModule.tool_name || "--"}</span>
                      </div>
                      <div className={styles.infoRow}>
                        <strong>Created By:</strong>
                        <span>{selectedPendingModule.created_by || "--"}</span>
                      </div>
                      <div className={styles.infoRow}>
                        <strong>Created On:</strong>
                        <span>{formatDate(selectedPendingModule.created_on)}</span>
                      </div>
                      <div className={styles.infoRow}>
                        <strong>Module:</strong>
                        <span>{selectedPendingModule.module_name || "--"}</span>
                      </div>
                    </div>
                  </div>
                </div>
                {/* Right side - Code Preview */}
                <div className={styles.modalRight}>
                  <div className={styles.codeLabel}>Code Preview:</div>
                  <div className={styles.codeEditorContainer}>
                    <CodeEditor
                      mode="python"
                      codeToDisplay={selectedPendingModule.code_snippet || "# No code available"}
                      width="100%"
                      height="250px"
                      fontSize={14}
                      readOnly={true}
                      setOptions={{
                        enableBasicAutocompletion: false,
                        enableLiveAutocompletion: false,
                        enableSnippets: false,
                        showLineNumbers: true,
                        tabSize: 4,
                        useWorker: false,
                        wrap: false,
                      }}
                      className={styles.codeEditorFont}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>,
          document.body
        )}
      </>
    );
  }

  // --- INSTALLED MODULES UI (default) ---
  // Transform installed packages for DisplayCard1
  const transformedInstalled = filtered.map((pkg) => {
    const [moduleName, version] = pkg.split("==");
    return {
      module_name: moduleName || pkg,
      version: version ? `Version: ${version}` : "",
      category: "uncategorized", // Hides footer
    };
  });

  return (
    <>
      <SummaryLine visibleCount={filtered.length} totalCount={installed.length} />
      <div className="listWrapper">
        {loading ? (
          <Loader />
        ) : filtered.length > 0 ? (
          <DisplayCard1
            data={transformedInstalled}
            cardNameKey="module_name"
            cardDescriptionKey="version"
            cardOwnerKey=""
            cardCategoryKey="category"
            emptyMessage="No installed modules found."
            loading={loading}
            showCreateCard={false}
            showButton={false}
            showCheckbox={false}
            showDeleteButton={false}
            footerButtonsConfig={[]}
            className="installedModulesCards"
          />
        ) : (
          <EmptyState
            filters={searchValue ? [`Search: ${searchValue}`] : []}
            onClearFilters={onClearSearch}
            message={searchValue ? "No installed modules found" : "No installed modules found"}
            subMessage={searchValue ? "" : "There are no modules installed yet"}
            showClearFilter={Boolean(searchValue)}
            showCreateButton={false}
          />
        )}
      </div>
    </>
  );
};

export default InstallationTab;
