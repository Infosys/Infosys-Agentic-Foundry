import React, { useState, useCallback, useEffect } from "react";
import ReactDOM from "react-dom";
import { getEmailFromToken } from "../../utils/jwtUtils";
import styles from "./SystemUtility.module.css";
import sliderStyles from "../commonComponents/ResourceSlider/ResourceSlider.module.css";
import { useMessage } from "../../Hooks/MessageContext";
import { useSystemUtilityService } from "../../services/systemUtilityService";
import SubHeader from "../commonComponents/SubHeader";
import PageLayout from "../../iafComponents/GlobalComponents/PageLayout";
import Button from "../../iafComponents/GlobalComponents/Buttons/Button";
import SVGIcons from "../../Icons/SVGIcons";
import DeleteModal from "../commonComponents/DeleteModal";
import Toggle from "../commonComponents/Toggle";
import Skeleton, { SkeletonList } from "../commonComponents/Skeleton";
import EmptyState from "../commonComponents/EmptyState";
import InfoTag from "../commonComponents/InfoTag";
import TextField from "../../iafComponents/GlobalComponents/TextField/TextField";

const SystemUtility = () => {
  return (
    <div className="pageContainer">
      <SubHeader
        heading="System Utility"
        activeTab="system-utility"
        showSearch={false}
        showRefreshButton={false}
        showPlusButton={false}
      />
      <PageLayout>
        <SystemUtilityContent />
      </PageLayout>
    </div>
  );
};

/**
 * Embeddable version without its own SubHeader/PageLayout wrapper.
 * Used when rendered inside AdminScreenNew.
 */
export const SystemUtilityContent = () => {
  const { addMessage } = useMessage();
  const {
    backupAndExport,
    cleanupPreview,
    cleanupExecute,
    listCleanupReports,
    getReportDownloadUrl,
    downloadReport,
  } = useSystemUtilityService();

  const [backupLoading, setBackupLoading] = useState(false);
  const [sendEmails, setSendEmails] = useState(true);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewData, setPreviewData] = useState(null);
  const [executeLoading, setExecuteLoading] = useState(false);
  const [executeResult, setExecuteResult] = useState(null);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [reports, setReports] = useState(null);
  const [reportsLoading, setReportsLoading] = useState(false);
  const [backupSuccess, setBackupSuccess] = useState(false);
  const [reportSearch, setReportSearch] = useState("");
  const [activeReportTab, setActiveReportTab] = useState("preview");
  const [showPreviewSlider, setShowPreviewSlider] = useState(false);
  const [isSliderCollapsed, setIsSliderCollapsed] = useState(false);

  const fetchReports = useCallback(async () => {
    setReportsLoading(true);
    try {
      const res = await listCleanupReports();
      if (res && !res.error) {
        setReports(res);
      } else {
        addMessage(res?.error || "Failed to load reports", "error");
      }
    } catch {
      addMessage("Failed to load reports", "error");
    } finally {
      setReportsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    fetchReports();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isErrorResponse = (res) => {
    if (!res) return true;
    if (res.statusCode || res.code) return true;
    if (res.detail) return true;
    if (res.error) return true;
    return false;
  };

  const getErrorText = (res, fallback) => {
    if (!res) return fallback;
    return res.detail || res.error || res.message || fallback;
  };

  const handleBackup = async () => {
    setBackupLoading(true);
    setBackupSuccess(false);
    try {
      const res = await backupAndExport(getEmailFromToken());
      if (isErrorResponse(res)) {
        addMessage(getErrorText(res, "Backup & export failed"), "error");
      } else {
        setBackupSuccess(true);
        addMessage(res.message || "Backup & export completed successfully", "success");
      }
    } catch {
      addMessage("Backup & export failed", "error");
    } finally {
      setBackupLoading(false);
    }
  };

  const handlePreview = async () => {
    setPreviewLoading(true);
    setPreviewData(null);
    setExecuteResult(null);
    try {
      const res = await cleanupPreview(sendEmails);
      if (isErrorResponse(res)) {
        addMessage(getErrorText(res, "Failed to load preview"), "error");
      } else {
        setPreviewData(res);
        setShowPreviewSlider(true);
        setIsSliderCollapsed(false);
        addMessage(res.message || "Preview loaded", "success");
      }
    } catch {
      addMessage("Failed to load cleanup preview", "error");
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleExecute = async () => {
    setShowConfirmModal(false);
    setExecuteLoading(true);
    try {
      const res = await cleanupExecute();
      if (isErrorResponse(res)) {
        addMessage(getErrorText(res, "Cleanup execution failed"), "error");
      } else {
        setExecuteResult(res);
        setPreviewData(null);
        setShowPreviewSlider(true);
        setIsSliderCollapsed(false);
        addMessage(res.message || "Cleanup executed successfully", "success");
        fetchReports();
      }
    } catch {
      addMessage("Cleanup execution failed", "error");
    } finally {
      setExecuteLoading(false);
    }
  };

  const handleDownloadReport = async (downloadUrl) => {
    try {
      const blob = await downloadReport(downloadUrl);
      if (!blob) throw new Error("Failed to download report");
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = downloadUrl.split("/").pop() || "report.xlsx";
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      a.remove();
    } catch {
      addMessage("Failed to download report", "error");
    }
  };

  const formatFileSize = (bytes) => {
    if (!bytes) return "—";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const formatDate = (dateString) => {
    if (!dateString) return "—";
    try {
      return new Date(dateString).toLocaleString();
    } catch {
      return dateString;
    }
  };

  const relativeTime = (dateString) => {
    if (!dateString) return "";
    try {
      const diff = Date.now() - new Date(dateString).getTime();
      const mins = Math.floor(diff / 60000);
      if (mins < 1) return "just now";
      if (mins < 60) return `${mins}m ago`;
      const hrs = Math.floor(mins / 60);
      if (hrs < 24) return `${hrs}h ago`;
      const days = Math.floor(hrs / 24);
      return `${days}d ago`;
    } catch {
      return "";
    }
  };

  /** Filter reports by search term */
  const filterReports = (list) => {
    if (!list || !reportSearch.trim()) return list;
    const q = reportSearch.toLowerCase();
    return list.filter((r) => r.filename?.toLowerCase().includes(q));
  };

  const cleanupReportsFiltered = filterReports(reports?.cleanup_reports);
  const deletionReportsFiltered = filterReports(reports?.deletion_reports);
  const totalReportCount = (reports?.cleanup_reports?.length || 0) + (reports?.deletion_reports?.length || 0);

  return (
    <>
      <div className={styles.container}>
        {/* ===== TOP ROW: 2-column grid for Backup + Cleanup ===== */}
        <div className={styles.topGrid}>
          {/* ===== SECTION 1: BACKUP & EXPORT ===== */}
          <div className={styles.section} aria-label="Backup and Export">
            <div className={styles.backupHeaderRow}>
              <div className={styles.sectionHeader}>
                <div className={`${styles.sectionIcon} ${styles.backup}`}>
                  <SVGIcons icon="download" width={16} height={16} />
                </div>
                <h3 className={styles.sectionTitle}>Backup & Export</h3>
                <InfoTag message="Creates a downloadable archive of all your agents, tools, validators, servers, and workflow configurations." />
              </div>
              <Button type="primary" onClick={handleBackup} disabled={backupLoading} loading={backupLoading}>
                {backupLoading ? "Exporting..." : "Export Backup"}
              </Button>
            </div>
            {backupSuccess && (
              <div className={styles.successBanner} role="status" aria-live="polite">
                <SVGIcons icon="check-success" width={16} height={16} />
                <span>Backup exported successfully. Check your downloads.</span>
              </div>
            )}
          </div>

          {/* ===== SECTION 2: SYSTEM CLEANUP ===== */}
          <div className={styles.section} aria-label="System Cleanup">
            <div className={styles.cleanupHeaderRow}>
              <div className={styles.sectionHeader}>
                <div className={`${styles.sectionIcon} ${styles.cleanup}`}>
                  <SVGIcons icon="trash" width={16} height={16} />
                </div>
                <h3 className={styles.sectionTitle}>System Cleanup</h3>
                <InfoTag message="Scans for unused resources that are not part of any active workflow or agent configuration and removes them permanently." />
              </div>
              <div className={styles.cleanupActions}>
                <div className={styles.toggleRow}>
                  <span className={styles.toggleLabel}>Notify</span>
                  <Toggle value={sendEmails} onChange={(e) => setSendEmails(e.target.checked)} />
                </div>
                <Button type="primary" onClick={handlePreview} disabled={previewLoading || executeLoading || !backupSuccess} loading={previewLoading}>
                  {previewLoading ? "Scanning..." : previewData ? "Re-scan" : "Preview Cleanup"}
                </Button>
              </div>
            </div>
            {(previewData || executeResult) && <div className={styles.sectionActions}>
              {previewData && (
                <Button type="primary" onClick={() => setShowConfirmModal(true)} disabled={executeLoading || !previewData?.summary?.total}>
                  Execute
                </Button>
              )}
              {(previewData || executeResult) && !showPreviewSlider && (
                <Button type="secondary" onClick={() => { setShowPreviewSlider(true); setIsSliderCollapsed(false); }}>
                  Results
                </Button>
              )}
              {(previewData || executeResult) && (
                <Button type="secondary" onClick={() => { setPreviewData(null); setExecuteResult(null); setShowPreviewSlider(false); }}>
                  Reset
                </Button>
              )}
            </div>}
            {executeLoading && (
              <div className={styles.inlineLoader}>
                <Skeleton variant="text" width="100%" height={14} count={3} />
              </div>
            )}
          </div>
        </div>

        {/* ===== SECTION 3: CLEANUP REPORTS (full width) ===== */}
        <div className={styles.section} aria-label="Cleanup Reports">
          {/* Header row: title left, actions right */}
          <div className={styles.reportsHeaderRow}>
            <div className={styles.sectionHeader}>
              <div className={`${styles.sectionIcon} ${styles.reports}`}>
                <SVGIcons icon="file" width={16} height={16} />
              </div>
              <h3 className={styles.sectionTitle}>Cleanup Reports</h3>
              {totalReportCount > 0 && (
                <span className={styles.countBadge}>{totalReportCount}</span>
              )}
              <InfoTag message="Historical reports generated after each cleanup preview or execution. Reports are stored as downloadable Excel files." />
            </div>
            <div className={styles.reportsActions}>
              {totalReportCount >= 0 && (
                <div className={styles.reportSearchWrapper}>
                  <TextField
                    placeholder="Search reports..."
                    value={reportSearch}
                    onChange={(e) => setReportSearch(e.target.value)}
                    onClear={() => setReportSearch("")}
                    showClearButton={true}
                    showSearchButton={true}
                    onSearch={() => { }}
                    aria-label="Search reports"
                  />
                </div>
              )}
              <button
                className={styles.refreshBtn}
                onClick={fetchReports}
                disabled={reportsLoading}
                title="Refresh reports"
              >
                <SVGIcons icon="rotate-ccw" width={15} height={15} />
              </button>
            </div>
          </div>

          {/* Tabs */}
          <div className={styles.reportTabs}>
            <button
              className={`${styles.reportTab} ${activeReportTab === "preview" ? styles.reportTabActive : ""}`}
              onClick={() => setActiveReportTab("preview")}
            >
              Preview Reports
              <span className={styles.tabCount}>{cleanupReportsFiltered?.length || 0}</span>
            </button>
            <button
              className={`${styles.reportTab} ${activeReportTab === "deletion" ? styles.reportTabActive : ""}`}
              onClick={() => setActiveReportTab("deletion")}
            >
              Deletion Reports
              <span className={styles.tabCount}>{deletionReportsFiltered?.length || 0}</span>
            </button>
          </div>

          {/* Tab content */}
          {reportsLoading && (
            <div className={styles.reportsLoaderWrapper}>
              <SkeletonList count={3} />
            </div>
          )}
          {reports && !reportsLoading && (
            <div className={styles.reportsContainer}>
              {(activeReportTab === "preview" ? cleanupReportsFiltered : deletionReportsFiltered)?.length > 0 ? (
                <div className={styles.reportsList}>
                  {(activeReportTab === "preview" ? cleanupReportsFiltered : deletionReportsFiltered).map((report) => (
                    <div className={styles.reportItem} key={report.filename}>
                      <div className={styles.reportInfo}>
                        <SVGIcons icon="file" width={16} height={16} />
                        <div>
                          <span className={styles.reportFilename}>{report.filename}</span>
                          <span className={styles.reportMeta}>
                            {formatFileSize(report.size)} · {formatDate(report.modified)}
                            {relativeTime(report.modified) && <span className={styles.relativeTime}> ({relativeTime(report.modified)})</span>}
                          </span>
                        </div>
                      </div>
                      <button className={styles.downloadLink} onClick={() => handleDownloadReport(report.download_url)}>
                        <SVGIcons icon="download" width={14} height={14} /> Download
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState
                  message={reportSearch ? "No matching reports" : activeReportTab === "preview" ? "No cleanup preview reports" : "No deletion reports"}
                  subMessage={reportSearch ? "Try a different search term." : activeReportTab === "preview" ? "Run a cleanup preview to generate your first report." : "Execute a cleanup to generate a deletion report."}
                  showClearFilter={false}
                  showCreateButton={false}
                />
              )}
            </div>
          )}
        </div>
      </div>

      <DeleteModal show={showConfirmModal} onClose={() => setShowConfirmModal(false)}>
        <div className={styles.deleteConfirmIcon}>
          <SVGIcons icon="warnings" width={32} height={32} color="#ef4444" />
        </div>
        <h3 className={styles.deleteConfirmTitle}>Delete Unused Resources?</h3>
        <p className={styles.deleteConfirmMessage}>
          <strong>{previewData?.summary?.total || 0}</strong> items will be permanently removed. This action cannot be undone.
        </p>
        <div className={styles.deleteConfirmActions}>
          <button className={styles.deleteConfirmCancelBtn} onClick={() => setShowConfirmModal(false)}>
            Cancel
          </button>
          <button className={styles.deleteConfirmDeleteBtn} onClick={handleExecute}>
            Delete
          </button>
        </div>
      </DeleteModal>

      {/* ===== CLEANUP RESULTS SLIDER ===== */}
      {(showPreviewSlider && (previewData || executeResult)) &&
        ReactDOM.createPortal(
          <>
            {/* Backdrop */}
            {!isSliderCollapsed && (
              <div
                className={`${sliderStyles.sliderBackdrop} ${sliderStyles.visible}`}
                onClick={() => {
                  setShowPreviewSlider(false);
                  setIsSliderCollapsed(false);
                }}
              />
            )}

            {/* Slider Panel */}
            <div
              className={`${sliderStyles.sliderOverlay} ${styles.cleanupSlider} ${isSliderCollapsed ? sliderStyles.collapsed : ""}`}
              role="dialog"
              aria-modal={!isSliderCollapsed}
              aria-label="Cleanup results panel"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Collapse Toggle */}
              <button
                className={`${sliderStyles.sliderToggle} ${styles.cleanupSliderToggle} ${isSliderCollapsed ? sliderStyles.toggleCollapsed : ""}`}
                onClick={() => setIsSliderCollapsed((prev) => !prev)}
                aria-label={isSliderCollapsed ? "Expand panel" : "Collapse panel"}
                title={isSliderCollapsed ? "Expand panel" : "Collapse panel"}
              >
                <SVGIcons icon="chevronRight" width={16} height={16} color="currentColor" />
              </button>

              {/* Header */}
              <div className={sliderStyles.sliderHeader}>
                <h2 className={sliderStyles.sliderTitle}>
                  {executeResult ? "Cleanup Results" : "Preview Results"}
                </h2>
                <button
                  className="closeBtn"
                  onClick={() => {
                    setShowPreviewSlider(false);
                    setIsSliderCollapsed(false);
                  }}
                  aria-label="Close panel"
                  title="Close"
                >
                  <SVGIcons icon="close-x" width={20} height={20} color="currentColor" />
                </button>
              </div>

              {/* Content */}
              <div className={styles.sliderContent}>
                {/* Preview Summary */}
                {previewData && previewData.summary && (
                  <div className={styles.sliderSection}>
                    <div className={styles.summaryGrid}>
                      {Object.entries(previewData.summary)
                        .filter(([key]) => key !== "total")
                        .map(([key, value]) => (
                          <div className={`${styles.summaryItem} ${value > 0 ? styles.summaryItemWarning : ""}`} key={key}>
                            <div className={styles.summaryItemLabel}>{key.replace(/_/g, " ")}</div>
                            <div className={styles.summaryItemValue}>{value}</div>
                          </div>
                        ))}
                      <div className={`${styles.summaryItem} ${styles.summaryItemTotal}`}>
                        <div className={styles.summaryItemLabel}>Total</div>
                        <div className={styles.summaryItemValue}>{previewData.summary.total}</div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Execute Result */}
                {executeResult && (
                  <div className={styles.sliderSection}>
                    <p className={styles.sliderSectionMessage}>
                      <SVGIcons icon="check-success" width={14} height={14} />
                      {executeResult.message}
                    </p>
                    {executeResult.deleted_counts && (
                      <div className={styles.resultGrid}>
                        {Object.entries(executeResult.deleted_counts).map(([key, value]) => (
                          <div className={styles.resultItem} key={key}>
                            <span className={styles.resultItemLabel}>{key.replace(/_/g, " ")}</span>
                            <span className={styles.resultItemValue}>{value}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {executeResult.related_cleanup && (
                      <div className={styles.sliderSubSection}>
                        <h5 className={styles.sliderSubTitle}>Related Cleanup</h5>
                        <div className={styles.resultGrid}>
                          {Object.entries(executeResult.related_cleanup).map(([key, value]) => (
                            <div className={styles.resultItem} key={key}>
                              <span className={styles.resultItemLabel}>{key.replace(/_/g, " ")}</span>
                              <span className={styles.resultItemValue}>{value}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Footer */}
              <div className={`${sliderStyles.sliderFooter} ${styles.sliderFooter}`}>
                {previewData && (
                  <Button
                    type="primary"
                    onClick={() => {
                      setShowPreviewSlider(false);
                      setIsSliderCollapsed(false);
                      setShowConfirmModal(true);
                    }}
                    disabled={!previewData?.summary?.total}
                  >
                    <SVGIcons icon="trash" width={14} height={14} />
                    Execute Cleanup
                  </Button>
                )}
                {executeResult?.report_download_url && (
                  <Button type="primary" onClick={() => handleDownloadReport(executeResult.report_download_url)}>
                    <SVGIcons icon="download" width={14} height={14} />
                    Download Report
                  </Button>
                )}
                <Button
                  type="secondary"
                  onClick={() => {
                    setShowPreviewSlider(false);
                    setIsSliderCollapsed(false);
                  }}
                >
                  Close
                </Button>
              </div>
            </div>
          </>,
          document.body
        )}
    </>
  );
};

export default SystemUtility;