import React, { useState, useCallback, useEffect, useMemo } from "react";
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import Loader from "../commonComponents/Loader";
import EmptyState from "../commonComponents/EmptyState";
import ZoomPopup from "../commonComponents/ZoomPopup";
import SVGIcons from "../../Icons/SVGIcons";
import styles from "./ChatHistoryCleanup.module.css";

/**
 * ChatHistoryCleanup Component
 *
 * SuperAdmin tab that:
 * 1. Auto-fetches cleanup status (GET /utility/conversation-cleanup/status) on mount
 * 2. Shows a "Run Cleanup" button that opens a modal with days_threshold
 *    and recycle_retention_days fields, then POSTs to /utility/conversation-cleanup
 */
const ChatHistoryCleanup = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [sortConfig, setSortConfig] = useState({ key: null, direction: "asc" });

  // Modal state
  const [showModal, setShowModal] = useState(false);
  const [daysThreshold, setDaysThreshold] = useState(30);
  const [recycleRetentionDays, setRecycleRetentionDays] = useState(15);
  const [executing, setExecuting] = useState(false);

  // Zoom popup state for cell expand
  const [showZoom, setShowZoom] = useState(false);
  const [zoomTitle, setZoomTitle] = useState("");
  const [zoomContent, setZoomContent] = useState("");

  const { fetchData, postData } = useFetch();
  const { handleApiSuccess } = useErrorHandler();

  /**
   * Fetch conversation cleanup status — runs on mount
   */
  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const response = await fetchData(APIs.CONVERSATION_CLEANUP_STATUS);
      if (response) {
        setData(response);
      } else {
        setData(null);
        setError(true);
      }
    } catch {
      setData(null);
      setError(true);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  /**
   * Run conversation cleanup — POST with query params
   */
  const handleRunCleanup = async () => {
    setExecuting(true);
    try {
      const url = `${APIs.CONVERSATION_CLEANUP}?days_threshold=${encodeURIComponent(daysThreshold)}&recycle_retention_days=${encodeURIComponent(recycleRetentionDays)}`;
      const response = await postData(url);
      if (response) {
        handleApiSuccess(response, {
          fallbackMessage: "Conversation cleanup triggered successfully",
        });
        setShowModal(false);
        loadStatus();
      }
    } catch {
      // Error handled by useFetch (handleApiError)
    } finally {
      setExecuting(false);
    }
  };

  /**
   * Extract rows from the API response.
   */
  const rows = useMemo(() => {
    if (!data) return [];
    if (Array.isArray(data)) return data;

    for (const key of Object.keys(data)) {
      if (Array.isArray(data[key]) && data[key].length > 0 && typeof data[key][0] === "object") {
        return data[key];
      }
    }

    if (typeof data === "object" && Object.keys(data).length > 0) {
      return [data];
    }

    return [];
  }, [data]);

  /**
   * Extract unique column keys from all rows
   */
  const columns = useMemo(() => {
    if (rows.length === 0) return [];
    const allKeys = new Set();
    rows.forEach((row) => {
      Object.keys(row).forEach((key) => allKeys.add(key));
    });
    return Array.from(allKeys);
  }, [rows]);

  /**
   * Sort rows by clicked column
   */
  const sortedRows = useMemo(() => {
    if (!sortConfig.key) return rows;

    return [...rows].sort((a, b) => {
      const aVal = a[sortConfig.key];
      const bVal = b[sortConfig.key];

      if (aVal == null && bVal == null) return 0;
      if (aVal == null) return 1;
      if (bVal == null) return -1;

      if (typeof aVal === "number" && typeof bVal === "number") {
        return sortConfig.direction === "asc" ? aVal - bVal : bVal - aVal;
      }

      const aStr = String(aVal).toLowerCase();
      const bStr = String(bVal).toLowerCase();
      if (aStr < bStr) return sortConfig.direction === "asc" ? -1 : 1;
      if (aStr > bStr) return sortConfig.direction === "asc" ? 1 : -1;
      return 0;
    });
  }, [rows, sortConfig]);

  const handleSort = (columnKey) => {
    setSortConfig((prev) => ({
      key: columnKey,
      direction: prev.key === columnKey && prev.direction === "asc" ? "desc" : "asc",
    }));
  };

  const formatHeader = (key) => {
    return key.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
  };

  /**
   * Smart timestamp formatting (IST):
   * - < 1 min       → "Just now"
   * - < 1 hr        → "45 mins"
   * - Today (1hr+)  → "03:45 pm"
   * - Yesterday     → "Yesterday, 03:45 pm"
   * - < 30 days     → "5 days, 03:45 pm"
   * - ≥ 30 days     → "17 Mar, 03:45 pm"
   * - Older year    → "17 Mar 2024"
   */
  const formatTimestamp = (value) => {
    try {
      const date = new Date(value);
      if (isNaN(date.getTime())) return String(value);

      const now = new Date();
      const diffMs = now - date;
      const diffMins = Math.floor(diffMs / 60000);
      const diffHrs = Math.floor(diffMs / 3600000);
      const diffDays = Math.floor(diffMs / 86400000);

      const istOptions = { timeZone: "Asia/Kolkata" };

      const timeStr = date.toLocaleTimeString("en-IN", {
        timeZone: "Asia/Kolkata",
        hour: "2-digit",
        minute: "2-digit",
        hour12: true,
      });

      // < 1 minute → Just now
      if (diffMs >= 0 && diffMins < 1) {
        return "Just now";
      }

      // < 1 hour → show mins
      if (diffMs >= 0 && diffHrs < 1) {
        return `${diffMins} min${diffMins === 1 ? "" : "s"}`;
      }

      const istDateStr = date.toLocaleDateString("en-CA", istOptions);
      const todayStr = now.toLocaleDateString("en-CA", istOptions);

      const yesterday = new Date(now);
      yesterday.setDate(yesterday.getDate() - 1);
      const yesterdayStr = yesterday.toLocaleDateString("en-CA", istOptions);

      // Today → show time
      if (istDateStr === todayStr) {
        return timeStr;
      }

      // Yesterday → Yesterday, time
      if (istDateStr === yesterdayStr) {
        return `Yesterday, ${timeStr}`;
      }

      // < 30 days → days and time
      if (diffMs >= 0 && diffDays < 30) {
        return `${diffDays} day${diffDays === 1 ? "" : "s"}, ${timeStr}`;
      }

      const istYear = Number(istDateStr.split("-")[0]);
      const currentYear = Number(todayStr.split("-")[0]);

      // Same year (≥ 30 days) → date month and time
      if (istYear === currentYear) {
        const dayMonth = date.toLocaleDateString("en-IN", {
          timeZone: "Asia/Kolkata",
          day: "2-digit",
          month: "short",
        });
        return `${dayMonth}, ${timeStr}`;
      }

      // Older year → date month year (no time)
      return date.toLocaleDateString("en-IN", {
        timeZone: "Asia/Kolkata",
        day: "2-digit",
        month: "short",
        year: "numeric",
      });
    } catch {
      return String(value);
    }
  };

  /**
   * Check if a column holds timestamp data
   */
  const isTimestampColumn = (key) => {
    const lower = key.toLowerCase();
    return lower.includes("_at") || lower.includes("date") || lower.includes("time") || lower.includes("timestamp");
  };

  const formatCell = (value, columnKey) => {
    if (value === null || typeof value === "undefined") return "—";
    if (columnKey && isTimestampColumn(columnKey)) return formatTimestamp(value);
    if (typeof value === "boolean") return value ? "Yes" : "No";
    if (Array.isArray(value)) return value.length > 0 ? value.join(", ") : "—";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  };

  const getStatusClass = (value) => {
    if (typeof value !== "string") return "";
    const lower = value.toLowerCase();
    if (["completed", "success", "done", "active", "cleaned", "true", "yes"].includes(lower)) {
      return styles.statusSuccess;
    }
    if (["failed", "error", "inactive", "false", "no"].includes(lower)) {
      return styles.statusError;
    }
    if (["pending", "in_progress", "running", "processing", "in progress"].includes(lower)) {
      return styles.statusPending;
    }
    return "";
  };

  /**
   * Get the most recent run_at timestamp for "Last Run" display
   */
  const lastRunDisplay = useMemo(() => {
    if (rows.length === 0) return null;
    const runAtKey = columns.find((col) => col.toLowerCase() === "run_at");
    if (!runAtKey) return null;
    const timestamps = rows
      .map((row) => row[runAtKey])
      .filter(Boolean)
      .map((val) => new Date(val))
      .filter((d) => !isNaN(d.getTime()));
    if (timestamps.length === 0) return null;
    const latest = new Date(Math.max(...timestamps.map((d) => d.getTime())));
    return formatTimestamp(latest.toISOString());
  }, [rows, columns]);

  /**
   * Open ZoomPopup to view full cell content
   */
  const handleCellExpand = (columnKey, value) => {
    setZoomTitle(formatHeader(columnKey));
    setZoomContent(formatCell(value));
    setShowZoom(true);
  };

  return (
    <div className={styles.container}>
      {loading && <Loader />}

      {/* Action Bar: Last Run (left) + Run Cleanup (right) */}
      {!loading && (
        <div className={styles.actionBar}>
          <div className={styles.lastRun}>
            {lastRunDisplay && (
              <>
                <span className={styles.lastRunLabel}>Last Run:</span>
                <span className={styles.lastRunValue}>{lastRunDisplay}</span>
              </>
            )}
          </div>
          <button
            className={styles.runButton}
            onClick={() => setShowModal(true)}
          >
            Run Cleanup
          </button>
        </div>
      )}

      {/* Table */}
      {!loading && sortedRows.length > 0 && (
        <div className={styles.tableWrapper}>
          <div className={styles.tableContainer}>
            <table className={styles.cleanupTable}>
              <thead>
                <tr>
                  {columns.map((col) => (
                    <th
                      key={col}
                      onClick={() => handleSort(col)}
                      className={sortConfig.key === col ? styles.sortedColumn : ""}
                    >
                      <div className={styles.thContent}>
                        {formatHeader(col)}
                        <span className={styles.sortIcon}>
                          {sortConfig.key === col
                            ? sortConfig.direction === "asc" ? "↑" : "↓"
                            : "⇅"}
                        </span>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((row, rowIdx) => (
                  <tr key={rowIdx}>
                    {columns.map((col) => {
                      const raw = row[col];
                      const display = formatCell(raw, col);
                      const statusClass = getStatusClass(typeof raw === "string" ? raw : "");
                      const showExpand = col.toLowerCase() === "message";
                      return (
                        <td key={col}>
                          <div className={styles.cellWrapper}>
                            <span
                              className={styles.cellText}
                              title={display}
                            >
                              {statusClass ? (
                                <span className={`${styles.statusBadge} ${statusClass}`}>
                                  {display}
                                </span>
                              ) : (
                                display
                              )}
                            </span>
                            {showExpand && display && display !== "—" && (
                              <button
                                type="button"
                                className={styles.expandIconBtn}
                                onClick={() => handleCellExpand(col, raw)}
                                title="View full content"
                              >
                                <SVGIcons icon="fa-solid fa-up-right-and-down-left-from-center" width={12} height={12} />
                              </button>
                            )}
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Empty State */}
      {!loading && (error || sortedRows.length === 0) && (
        <EmptyState
          message="No cleanup records found"
          subMessage="The conversation cleanup status returned no records."
          showCreateButton={false}
          showClearFilter={false}
        />
      )}

      {/* Zoom Popup for cell expand */}
      <ZoomPopup
        show={showZoom}
        onClose={() => setShowZoom(false)}
        title={zoomTitle}
        content={zoomContent}
        type="text"
        readOnly={true}
        hideFooter={true}
        showCopy={true}
      />

      {/* Run Cleanup Modal */}
      {showModal && (
        <div className={styles.modalOverlay} onClick={() => !executing && setShowModal(false)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h4>Run Conversation Cleanup</h4>
              <button
                className={styles.closeBtn}
                onClick={() => !executing && setShowModal(false)}
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            <div className={styles.formGroup}>
              <label htmlFor="daysThreshold">Days Threshold</label>
              <span className={styles.fieldHint}>Delete conversations older than this many days</span>
              <input
                id="daysThreshold"
                type="number"
                min="1"
                className={styles.formInput}
                value={daysThreshold}
                onChange={(e) => setDaysThreshold(Number(e.target.value))}
                disabled={executing}
              />
            </div>

            <div className={styles.formGroup}>
              <label htmlFor="recycleRetentionDays">Recycle Retention Days</label>
              <span className={styles.fieldHint}>Days to retain data in recycle bin before permanent deletion</span>
              <input
                id="recycleRetentionDays"
                type="number"
                min="1"
                className={styles.formInput}
                value={recycleRetentionDays}
                onChange={(e) => setRecycleRetentionDays(Number(e.target.value))}
                disabled={executing}
              />
            </div>

            <div className={styles.modalFooter}>
              <button
                className={styles.cancelBtn}
                onClick={() => setShowModal(false)}
                disabled={executing}
              >
                Cancel
              </button>
              <button
                className={styles.executeBtn}
                onClick={handleRunCleanup}
                disabled={executing || daysThreshold < 1 || recycleRetentionDays < 1}
              >
                {executing ? "Executing..." : "Execute"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ChatHistoryCleanup;
