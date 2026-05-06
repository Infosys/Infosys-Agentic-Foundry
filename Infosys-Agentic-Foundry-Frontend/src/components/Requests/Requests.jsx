import React, { useState, useEffect, useCallback } from "react";
import styles from "./Requests.module.css";
import { useRequestsService } from "../../services/requestsService";
import RaiseRequestModal from "./RaiseRequestModal";
import SubHeader from "../commonComponents/SubHeader";
import PageLayout from "../../iafComponents/GlobalComponents/PageLayout";
import Loader from "../commonComponents/Loader";
import EmptyState from "../commonComponents/EmptyState";
import ZoomPopup from "../commonComponents/ZoomPopup";
import SVGIcons from "../../Icons/SVGIcons";

/**
 * Requests Page — Table view matching AgentLearning / ResponseList pattern.
 */
const Requests = () => {
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState("all");
  const [zoomPopup, setZoomPopup] = useState({ open: false, title: "", content: "" });
  const { getMyRequests } = useRequestsService();

  // ──── Fetch requests ────
  const fetchRequests = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);

    try {
      const response = await getMyRequests();
      if (response?.success) {
        setRequests(response.requests || []);
      } else if (Array.isArray(response?.requests)) {
        setRequests(response.requests);
      } else if (Array.isArray(response)) {
        setRequests(response);
      } else {
        setRequests([]);
      }
    } catch {
      // Error handled by useFetch (handleApiError)
      setRequests([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    fetchRequests();
  }, [fetchRequests]);

  // ──── Helpers ────
  const getStatusClass = (status) => {
    const s = (status || "").toLowerCase();
    if (s === "approved") return styles.statusApproved;
    if (s === "rejected") return styles.statusRejected;
    return styles.statusPending;
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return "—";
    const d = new Date(dateStr);
    const date = d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
    const time = d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
    return `${date}, ${time}`;
  };

  // ──── Filtered requests (search + status filter) ────
  const filteredRequests = requests.filter((req) => {
    const matchesSearch = searchQuery
      ? (req.department_name || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
      (req.assigned_role || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
      (req.reviewed_by || "").toLowerCase().includes(searchQuery.toLowerCase())
      : true;
    const matchesFilter =
      activeFilter === "all" || (req.status || "pending").toLowerCase() === activeFilter;
    return matchesSearch && matchesFilter;
  });

  const statusCounts = {
    all: requests.length,
    approved: requests.filter((r) => r.status?.toLowerCase() === "approved").length,
    pending: requests.filter((r) => r.status?.toLowerCase() === "pending").length,
    rejected: requests.filter((r) => r.status?.toLowerCase() === "rejected").length,
  };

  const handleSearch = (query) => setSearchQuery(query || "");
  const handleClearSearch = () => setSearchQuery("");

  // ──── Render ────
  return (
    <div className="pageContainer">
      <SubHeader
        heading="My Requests"
        showSearch
        searchValue={searchQuery}
        onSearch={handleSearch}
        clearSearch={handleClearSearch}
        showPlusButton={false}
        showRefreshButton
        handleRefresh={() => fetchRequests(true)}
        secondaryButtonLabel="Raise Request"
        onSecondaryButtonClick={() => setShowModal(true)}
      />

      {/* Status filter chips */}
      {!loading && requests.length > 0 && (
        <div className={styles.filterBar}>
          {["all", "approved", "pending", "rejected"].map((filter) => (
            <button
              key={filter}
              type="button"
              className={`${styles.filterButton} ${activeFilter === filter ? styles.filterButtonActive : ""}`}
              onClick={() => setActiveFilter(filter)}
            >
              {filter.charAt(0).toUpperCase() + filter.slice(1)} ({statusCounts[filter]})
            </button>
          ))}
        </div>
      )}

      <PageLayout>
        <div className={`listWrapper ${styles.requestsListWrapper} ${refreshing ? styles.refreshing : ""}`}>
          <div className={styles.tableContainer}>
            {loading ? (
              <Loader />
            ) : requests.length === 0 ? (
              <EmptyState
                message="No requests yet. Click 'Raise Request' to get started."
                icon="fa-inbox"
              />
            ) : filteredRequests.length === 0 ? (
              <EmptyState
                message="No requests match your current search or filter."
                icon="fa-inbox"
              />
            ) : (
              <table className={styles.requestsTable}>
                <thead>
                  <tr>
                    <th className={styles.thSno}>S.No</th>
                    <th className={styles.thDepartment}>Department</th>
                    <th className={styles.thRole}>Role</th>
                    <th className={styles.thStatus}>Status</th>
                    <th className={styles.thReviewedBy}>Reviewed By</th>
                    <th className={styles.thReviewedAt}>Reviewed At</th>
                    <th className={styles.thRequestedAt}>Requested On</th>
                    <th className={styles.thReason}>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRequests.map((req, index) => {
                    const status = (req.status || "pending").toLowerCase();
                    return (
                      <tr key={req.id} className={styles.tableRow}>
                        <td className={styles.tdSno}>{index + 1}</td>
                        <td className={styles.tdDepartment} title={req.department_name || ""}>
                          <span className={styles.cellText}>{req.department_name || "—"}</span>
                        </td>
                        <td className={styles.tdRole} title={req.assigned_role || ""}>
                          <span className={styles.cellText}>{req.assigned_role || "—"}</span>
                        </td>
                        <td className={styles.tdStatus}>
                          <span className={`${styles.statusBadge} ${getStatusClass(status)}`}>
                            {status}
                          </span>
                        </td>
                        <td className={styles.tdReviewedBy} title={req.reviewed_by || ""}>
                          <span className={styles.cellText}>{req.reviewed_by || "—"}</span>
                        </td>
                        <td className={styles.tdReviewedAt} title={formatDate(req.reviewed_at)}>
                          <span className={styles.cellText}>{formatDate(req.reviewed_at)}</span>
                        </td>
                        <td className={styles.tdRequestedAt} title={formatDate(req.created_at)}>
                          <span className={styles.cellText}>{formatDate(req.created_at)}</span>
                        </td>
                        <td className={styles.tdReason}>
                          {status === "rejected" && req.rejection_reason ? (
                            <div className={styles.reasonCellWrapper}>
                              <span className={styles.rejectionText}>{req.rejection_reason}</span>
                              <button
                                className={styles.expandIconBtn}
                                title="View full reason"
                                onClick={() =>
                                  setZoomPopup({
                                    open: true,
                                    title: "Rejection Reason",
                                    content: req.rejection_reason,
                                  })
                                }
                              >
                                <SVGIcons
                                  icon="fa-solid fa-up-right-and-down-left-from-center"
                                  width={12}
                                  height={12}
                                />
                              </button>
                            </div>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </PageLayout>

      {/* Raise Request Modal */}
      {showModal && (
        <RaiseRequestModal
          existingRequests={requests}
          onClose={() => setShowModal(false)}
          onSuccess={() => {
            setShowModal(false);
            fetchRequests(true);
          }}
        />
      )}

      {/* Zoom Popup for full rejection reason */}
      {zoomPopup.open && (
        <ZoomPopup
          show={true}
          title={zoomPopup.title}
          content={zoomPopup.content}
          type="text"
          readOnly={true}
          hideFooter={true}
          onClose={() => setZoomPopup({ open: false, title: "", content: "" })}
        />
      )}
    </div>
  );
};

export default Requests;
