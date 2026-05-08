import React, { useState, useEffect, useRef, useMemo } from "react";
import styles from "./ConnectionManagementModal.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { useDatabases } from "./service/databaseService.js";
import { useDatabaseConnections } from "./hooks/useDatabaseConnections";
import { useMessage } from "../../Hooks/MessageContext";
import { useDatabase } from "./context/DatabaseContext";
import Loader from "../commonComponents/Loader.jsx";
import { Modal } from "../commonComponents/Modal";
import TextField from "../../iafComponents/GlobalComponents/TextField/TextField";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine";
import EmptyState from "../commonComponents/EmptyState.jsx";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";
import { DEFAULT_BLOCKED_SQL_COMMANDS } from "../../constant";

const ConnectionManagementModal = ({
  isOpen,
  onClose,
  availableConnections = [],
  isLoadingConnections = false,
  databaseType,
  onOpenRun,   // callback(connectionName, dbType) — opens QueryModal/CrudModal from parent
  onConnectionsChanged, // callback to notify parent that connections changed
}) => {
  // ===== View modes: "list" | "details" =====
  const [view, setView] = useState("list");

  // Connection list state
  const [searchQuery, setSearchQuery] = useState("");
  const [localSearch, setLocalSearch] = useState("");
  const [actionLoading, setActionLoading] = useState({}); // { [connName]: "activate"|"deactivate"|"disconnect" }
  const [pendingDisconnect, setPendingDisconnect] = useState(null); // conn to confirm disconnect

  // Details view state
  const [detailConnection, setDetailConnection] = useState(null);
  const [detailData, setDetailData] = useState(null); // full response from GET /get-db-details
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [blockedCommands, setBlockedCommands] = useState([]);
  const [blockedCommandInput, setBlockedCommandInput] = useState("");
  const [savingBlockedCommands, setSavingBlockedCommands] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [schemaExpanded, setSchemaExpanded] = useState(false);
  const [samplesExpanded, setSamplesExpanded] = useState(false);

  const { handleDisconnect, handleDeactivate, handleActivate: handleActivateConnection } = useDatabaseConnections();
  const { addMessage, setShowPopup } = useMessage();
  const { getActivePostgresConnections, getActiveMySQLConnections, getActiveSQLiteConnections, getActiveMongoConnections, fetchActiveConnections } = useDatabase();
  const [apiConnections, setApiConnections] = useState([]);
  const [loadingApiConnections, setLoadingApiConnections] = useState(false);
  const { fetchConnections, getDbDetails, getBlockedCommands, updateBlockedCommands, regenerateSchema } = useDatabases();
  const hasConnectionsRef = useRef(false);

  // Fetch connections on mount
  const fetchAllConnections = async () => {
    setLoadingApiConnections(true);
    try {
      const result = await fetchConnections();
      if (result.success) {
        setApiConnections(result.data.connections || result.data || []);
      } else {
        setApiConnections([]);
      }
    } catch {
      setApiConnections([]);
    } finally {
      setLoadingApiConnections(false);
    }
  };

  useEffect(() => {
    if (!hasConnectionsRef.current) {
      hasConnectionsRef.current = true;
      fetchAllConnections();
    }
  }, []);

  // Helper functions (must be defined before useMemos that reference them)
  const getConnName = (conn) => conn.connection_name || conn.name || conn.connectionName || "";
  const getConnType = (conn) => (conn.connection_database_type || conn.type || conn.databaseType || "").toLowerCase();

  // Get all active connection names (must be defined before filteredConnections)
  const activeConnectionNames = useMemo(() => {
    return [
      ...getActivePostgresConnections(),
      ...getActiveMySQLConnections(),
      ...getActiveSQLiteConnections(),
      ...getActiveMongoConnections(),
    ];
  }, [getActivePostgresConnections, getActiveMySQLConnections, getActiveSQLiteConnections, getActiveMongoConnections]);

  const isActive = (conn) => activeConnectionNames.includes(getConnName(conn));

  // Filter connections by databaseType, then by search, sort active to top
  const typeFilteredConnections = useMemo(() => {
    return databaseType
      ? apiConnections.filter((conn) => (conn.connection_database_type || conn.type || "").toLowerCase() === databaseType.toLowerCase())
      : apiConnections;
  }, [apiConnections, databaseType]);

  const filteredConnections = useMemo(() => {
    let conns = typeFilteredConnections;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      conns = conns.filter((conn) => {
        const name = (conn.connection_name || conn.name || "").toLowerCase();
        const type = (conn.connection_database_type || conn.type || "").toLowerCase();
        return name.includes(q) || type.includes(q);
      });
    }
    // Sort active connections to the top
    return [...conns].sort((a, b) => {
      const aActive = activeConnectionNames.includes(getConnName(a)) ? 0 : 1;
      const bActive = activeConnectionNames.includes(getConnName(b)) ? 0 : 1;
      return aActive - bActive;
    });
  }, [typeFilteredConnections, searchQuery, activeConnectionNames]);

  // ===== Connection actions =====
  const handleAction = async (conn, action) => {
    const connName = getConnName(conn);
    const connType = getConnType(conn);
    setActionLoading((prev) => ({ ...prev, [connName]: action }));
    try {
      if (action === "activate") {
        await handleActivateConnection(connName);
      } else if (action === "deactivate") {
        await handleDeactivate(connName, connType);
      } else if (action === "disconnect") {
        await handleDisconnect(connName, connType);
        setApiConnections((prev) => prev.filter((c) => getConnName(c) !== connName));
      }
      // Refresh active connections
      if (typeof fetchActiveConnections === "function") {
        await fetchActiveConnections();
      }
      // Notify parent to refresh its connection data
      if (typeof onConnectionsChanged === "function") {
        onConnectionsChanged();
      }
    } catch (error) {
      addMessage(`Error: ${error.message || "Action failed"}`, "error");
    } finally {
      setActionLoading((prev) => ({ ...prev, [connName]: null }));
    }
  };

  // ===== Details view: fetch full connection info =====
  const openDetails = (conn) => {
    setDetailConnection(conn);
    setView("details");
    setSchemaExpanded(false);
    setSamplesExpanded(false);
    loadDetails(getConnName(conn));
  };

  const loadDetails = async (connectionName) => {
    setLoadingDetails(true);
    setDetailData(null);
    try {
      const result = await getDbDetails(connectionName);
      if (result.success && result.data) {
        const data = result.data;
        setDetailData(data);
        // Initialize blocked commands from detail response
        const commands = Array.isArray(data.blocked_commands) ? data.blocked_commands : [];
        setBlockedCommands(commands);
      } else {
        setDetailData(null);
        setBlockedCommands([]);
      }
    } catch {
      setDetailData(null);
      setBlockedCommands([]);
    } finally {
      setLoadingDetails(false);
    }
  };

  const handleSaveBlockedCommands = async () => {
    if (!detailConnection) return;
    setSavingBlockedCommands(true);
    try {
      const result = await updateBlockedCommands(getConnName(detailConnection), blockedCommands);
      if (result.success) {
        addMessage("Blocked SQL commands updated successfully", "success");
      } else {
        addMessage(result.error || "Failed to update blocked commands", "error");
      }
    } catch {
      addMessage("Failed to update blocked commands", "error");
    } finally {
      setSavingBlockedCommands(false);
    }
  };

  const handleAddBlockedCommand = () => {
    const cmd = blockedCommandInput.trim().toUpperCase();
    if (cmd && !blockedCommands.includes(cmd)) {
      setBlockedCommands((prev) => [...prev, cmd]);
      setBlockedCommandInput("");
    }
  };

  const handleRemoveBlockedCommand = (cmd) => {
    setBlockedCommands((prev) => prev.filter((c) => c !== cmd));
  };

  const handleResetToDefaults = () => {
    // Prefer API-provided defaults, fallback to local constant
    const defaults = detailData?.default_blocked_commands;
    setBlockedCommands(Array.isArray(defaults) ? [...defaults] : [...DEFAULT_BLOCKED_SQL_COMMANDS]);
  };

  const handleRegenerateSchema = async () => {
    if (!detailConnection) return;
    setIsRegenerating(true);
    try {
      const result = await regenerateSchema(getConnName(detailConnection));
      if (result.success) {
        addMessage("Schema regenerated successfully", "success");
        // Refresh details to reflect new schema
        loadDetails(getConnName(detailConnection));
      } else {
        addMessage(result.error || "Failed to regenerate schema", "error");
      }
    } catch {
      addMessage("Failed to regenerate schema", "error");
    } finally {
      setIsRegenerating(false);
    }
  };

  const handleRunClick = (conn) => {
    const connName = getConnName(conn);
    const connType = getConnType(conn);
    if (onOpenRun) {
      onOpenRun(connName, connType);
    }
  };

  const backToList = () => {
    setView("list");
    setDetailConnection(null);
    setDetailData(null);
    setBlockedCommands([]);
    setBlockedCommandInput("");
    setSchemaExpanded(false);
    setSamplesExpanded(false);
  };

  useEffect(() => {
    if (!isLoadingConnections) {
      setShowPopup(true);
    } else {
      setShowPopup(false);
    }
  }, [isLoadingConnections, setShowPopup]);

  // ===== RENDER =====
  return (
    <>
      <Modal isOpen={isOpen} onClose={onClose} size="lg" ariaLabel="Manage Database Connections" className={styles.managementModal}>
        {(isLoadingConnections || loadingApiConnections) && <Loader />}

        {/* ===== LIST VIEW ===== */}
        {view === "list" && (
          <>
            <div className={styles.modalHeader}>
              <h2 className={styles.modalTitle}>
                Manage Connections{databaseType ? ` — ${databaseType}` : ""}
              </h2>
            </div>

            {/* Search bar */}
            <div className={styles.searchBarContainer}>
              <TextField
                placeholder="Search connections..."
                value={localSearch}
                onChange={(e) => setLocalSearch(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") setSearchQuery(localSearch);
                }}
                onClear={() => {
                  setLocalSearch("");
                  setSearchQuery("");
                }}
                showClearButton={true}
                showSearchButton={true}
                onSearch={() => setSearchQuery(localSearch)}
                aria-label="Search connections"
              />
              <SummaryLine
                visibleCount={filteredConnections.length}
                totalCount={typeFilteredConnections.length}
                itemLabel="connections"
                showWhenEmpty={true}
              />
            </div>

            {/* Connection list */}
            <div className={styles.connectionList}>
              {filteredConnections.length === 0 ? (
                <EmptyState
                  message={searchQuery ? "No connections match your search" : "No connections found"}
                  subMessage={searchQuery ? "Try a different search term" : "Add a new connection to get started"}
                  filters={searchQuery ? [`Search: ${searchQuery}`] : []}
                  onClearFilters={() => {
                    setLocalSearch("");
                    setSearchQuery("");
                  }}
                  showClearFilter={!!searchQuery}
                  showCreateButton={false}
                />
              ) : (
                filteredConnections.map((conn) => {
                  const connName = getConnName(conn);
                  const connType = getConnType(conn);
                  const active = isActive(conn);
                  const loading = actionLoading[connName];
                  return (
                    <div key={connName} className={`${styles.connectionRow} ${active ? styles.connectionRowActive : ""}`}>
                      <div className={styles.connectionInfo}>
                        <div className={styles.connectionNameRow}>
                          <span className={styles.connectionName}>{connName}</span>
                          <span className={`${styles.statusDot} ${active ? styles.statusDotActive : styles.statusDotInactive}`} />
                          <span className={styles.statusLabel}>{active ? "Active" : "Inactive"}</span>
                        </div>
                        {connType && <span className={styles.connectionType}>{connType}</span>}
                      </div>
                      <div className={styles.connectionActions}>
                        {/* Activate / Deactivate */}
                        {active ? (
                          <button
                            className={`${styles.actionBtn} ${styles.actionBtnWarn}`}
                            onClick={() => handleAction(conn, "deactivate")}
                            disabled={!!loading}
                            title="Deactivate">
                            {loading === "deactivate" ? <Loader /> : <SVGIcons icon="close" width={14} height={14} />}
                          </button>
                        ) : (
                          <button
                            className={`${styles.actionBtn} ${styles.actionBtnSuccess}`}
                            onClick={() => handleAction(conn, "activate")}
                            disabled={!!loading}
                            title="Activate">
                            {loading === "activate" ? <Loader /> : <SVGIcons icon="check" width={14} height={14} />}
                          </button>
                        )}
                        {/* View Details - hidden
                        <button
                          className={`${styles.actionBtn} ${styles.actionBtnPrimary}`}
                          onClick={() => openDetails(conn)}
                          title="View Details">
                          <SVGIcons icon="eye" width={14} height={14} />
                        </button>
                        */}
                        {/* Disconnect */}
                        <button
                          className={`${styles.actionBtn} ${styles.actionBtnDanger}`}
                          onClick={() => setPendingDisconnect(conn)}
                          disabled={!!loading}
                          title="Disconnect">
                          {loading === "disconnect" ? <Loader /> : <SVGIcons icon="trash" width={18} height={18} />}
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </>
        )}

        {/* ===== DETAILS VIEW ===== */}
        {view === "details" && detailConnection && (
          <>
            <div className={styles.modalHeader}>
              <button type="button" className={styles.backBtn} onClick={backToList} title="Back to list">
                <SVGIcons icon="chevron-left" width={18} height={18} />
              </button>
              <h2 className={styles.modalTitle}>Details — {getConnName(detailConnection)}</h2>
            </div>

            {loadingDetails ? (
              <div className={styles.editBody}><Loader /></div>
            ) : !detailData ? (
              <div className={styles.editBody}>
                <p className={styles.sectionHint}>Failed to load connection details.</p>
              </div>
            ) : (
              <div className={styles.editBody}>
                {/* Status Indicators */}
                <div className={styles.detailStatusRow}>
                  <span className={`${styles.detailBadge} ${detailData.schema_exists ? styles.detailBadgeOk : styles.detailBadgeMissing}`}>
                    Schema: {detailData.schema_exists ? "Available" : "Not Found"}
                  </span>
                  <span className={`${styles.detailBadge} ${detailData.samples_exists ? styles.detailBadgeOk : styles.detailBadgeMissing}`}>
                    Samples: {detailData.samples_exists ? "Available" : "Not Found"}
                  </span>
                  {detailData.is_custom_blocked && (
                    <span className={`${styles.detailBadge} ${styles.detailBadgeCustom}`}>
                      Custom Blocked Commands
                    </span>
                  )}
                </div>

                {/* Schema Section */}
                <div className={styles.editSection}>
                  <div className={styles.sectionHeaderRow} onClick={() => setSchemaExpanded((prev) => !prev)} role="button" tabIndex={0}>
                    <h3 className={styles.sectionTitle}>Schema</h3>
                    <span className={schemaExpanded ? styles.chevronExpanded : styles.chevronCollapsed}>
                      <SVGIcons icon="chevron-down" width={14} height={14} />
                    </span>
                  </div>
                  {schemaExpanded && (
                    <div className={styles.detailCodeBlock}>
                      {detailData.schema ? (
                        <pre className={styles.detailPre}>
                          {typeof detailData.schema === "string" ? detailData.schema : JSON.stringify(detailData.schema, null, 2)}
                        </pre>
                      ) : (
                        <p className={styles.sectionHint}>No schema data available.</p>
                      )}
                    </div>
                  )}
                </div>

                {/* Samples Section */}
                <div className={styles.editSection}>
                  <div className={styles.sectionHeaderRow} onClick={() => setSamplesExpanded((prev) => !prev)} role="button" tabIndex={0}>
                    <h3 className={styles.sectionTitle}>Samples</h3>
                    <span className={samplesExpanded ? styles.chevronExpanded : styles.chevronCollapsed}>
                      <SVGIcons icon="chevron-down" width={14} height={14} />
                    </span>
                  </div>
                  {samplesExpanded && (
                    <div className={styles.detailCodeBlock}>
                      {detailData.samples ? (
                        <pre className={styles.detailPre}>
                          {typeof detailData.samples === "string" ? detailData.samples : JSON.stringify(detailData.samples, null, 2)}
                        </pre>
                      ) : (
                        <p className={styles.sectionHint}>No sample data available.</p>
                      )}
                    </div>
                  )}
                </div>

                {/* Schema Management */}
                <div className={styles.editSection}>
                  <h3 className={styles.sectionTitle}>Schema Management</h3>
                  <p className={styles.sectionHint}>
                    Regenerate the schema and sample data if the database structure has changed.
                  </p>
                  <button
                    className={`${styles.primaryBtn} ${isRegenerating ? styles.disabled : ""}`}
                    onClick={handleRegenerateSchema}
                    disabled={isRegenerating}>
                    <SVGIcons icon="fa-refresh" width={14} height={14} />
                    {isRegenerating ? "Regenerating..." : "Regenerate Schema"}
                  </button>
                </div>

                {/* Blocked SQL Commands */}
                <div className={styles.editSection}>
                  <h3 className={styles.sectionTitle}>Blocked SQL Commands</h3>
                  <p className={styles.sectionHint}>
                    These SQL commands will be blocked from execution on this connection.
                    {detailData.is_custom_blocked ? " (Custom list)" : " (Default list)"}
                  </p>
                  <div className={styles.blockedPills}>
                    {blockedCommands.map((cmd) => (
                      <span key={cmd} className={styles.blockedPill}>
                        {cmd}
                        <button type="button" className={styles.blockedPillRemove} onClick={() => handleRemoveBlockedCommand(cmd)}>
                          &times;
                        </button>
                      </span>
                    ))}
                    {blockedCommands.length === 0 && (
                      <span className={styles.sectionHint}>No blocked commands configured.</span>
                    )}
                  </div>
                  <div className={styles.blockedInputRow}>
                    <input
                      type="text"
                      className="input"
                      placeholder="Add SQL command (e.g. TRUNCATE)"
                      value={blockedCommandInput}
                      onChange={(e) => setBlockedCommandInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          handleAddBlockedCommand();
                        }
                      }}
                    />
                    <button type="button" className={styles.secondaryBtn} onClick={handleResetToDefaults} title="Reset to default blocked commands">
                      Defaults
                    </button>
                  </div>
                  <div className={styles.blockedActions}>
                    <button
                      className={`${styles.primaryBtn} ${savingBlockedCommands ? styles.disabled : ""}`}
                      onClick={handleSaveBlockedCommands}
                      disabled={savingBlockedCommands}>
                      {savingBlockedCommands ? "Saving..." : "Save Blocked Commands"}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </Modal>

      {pendingDisconnect && (
        <ConfirmationModal
          message={`Are you sure you want to disconnect "${getConnName(pendingDisconnect)}"? This action cannot be undone.`}
          onConfirm={() => {
            handleAction(pendingDisconnect, "disconnect");
            setPendingDisconnect(null);
          }}
          setShowConfirmation={() => setPendingDisconnect(null)}
        />
      )}
    </>
  );
};

export default ConnectionManagementModal;
