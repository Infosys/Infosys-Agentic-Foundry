import React, { useState, useEffect, useMemo, useCallback, useRef } from "react";
import styles from "./AgentLearning.module.css";
import SVGIcons from "../../Icons/SVGIcons.js";
import Loader from "../commonComponents/Loader.jsx";
import EmptyState from "../commonComponents/EmptyState";
import { APIs } from "../../constant";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios";
import FeedbackDetailModal from "./FeedbackDetailModal";
import ZoomPopup from "../commonComponents/ZoomPopup";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * AgentLearning Component
 * Displays a dashboard with stats cards and a filterable table of all agent feedbacks
 * Features:
 * - Stats cards showing total, approved, pending, and agents with feedback
 * - Multi-select agent name filter
 * - Table with agent name, feedback, learning, approval status, toggle, and view button
 * - View modal for full feedback details (read-only)
 */
const AgentLearning = ({ searchValue = "", selectedAgentTypes = [] }) => {
  // State management
  const [feedbacks, setFeedbacks] = useState([]);
  const [stats, setStats] = useState({
    total_feedback: 0,
    approved_feedback: 0,
    pending_feedback: 0,
    rejected_feedback: 0,
    agents_with_feedback: 0,
  });
  const [loading, setLoading] = useState(false);
  const [loadingStats, setLoadingStats] = useState(false);
  const [selectedFeedback, setSelectedFeedback] = useState(null);
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [statFilter, setStatFilter] = useState("all"); // "all", "approved", "pending", "rejected"

  // Zoom popup state for learning column
  const [showZoomPopup, setShowZoomPopup] = useState(false);
  const [zoomContent, setZoomContent] = useState("");
  const [zoomFeedback, setZoomFeedback] = useState(null);

  // Zoom popup state for feedback column (read-only)
  const [showFeedbackZoom, setShowFeedbackZoom] = useState(false);
  const [feedbackZoomContent, setFeedbackZoomContent] = useState("");

  const { addMessage, setShowPopup } = useMessage();
  const { fetchData, putData } = useFetch();
  const hasLoadedRef = useRef(false);

  // Filter feedbacks based on search value and approval status
  const filteredFeedbacks = useMemo(() => {
    let filtered = feedbacks;

    // Apply agent type filter
    if (selectedAgentTypes && selectedAgentTypes.length > 0) {
      filtered = filtered.filter((f) =>
        selectedAgentTypes.includes(f.agent_type)
      );
    }

    // Apply search filter (search in agent_name, feedback, lesson)
    if (searchValue.trim()) {
      const searchLower = searchValue.toLowerCase().trim();
      filtered = filtered.filter(
        (f) =>
          (f.agent_name && f.agent_name.toLowerCase().includes(searchLower)) ||
          (f.feedback && f.feedback.toLowerCase().includes(searchLower)) ||
          (f.lesson && f.lesson.toLowerCase().includes(searchLower))
      );
    }

    // Apply stat filter (status)
    if (statFilter === "approved") {
      filtered = filtered.filter((f) => f.status === "approve");
    } else if (statFilter === "pending") {
      filtered = filtered.filter((f) => f.status === "pending" || !f.status);
    } else if (statFilter === "rejected") {
      filtered = filtered.filter((f) => f.status === "reject");
    }

    return filtered;
  }, [feedbacks, searchValue, selectedAgentTypes, statFilter]);

  // Calculate filtered stats for display
  const filteredStats = useMemo(() => {
    let baseFiltered = feedbacks;
    // Apply agent type filter
    if (selectedAgentTypes && selectedAgentTypes.length > 0) {
      baseFiltered = baseFiltered.filter((f) =>
        selectedAgentTypes.includes(f.agent_type)
      );
    }
    // Apply search filter
    if (searchValue.trim()) {
      const searchLower = searchValue.toLowerCase().trim();
      baseFiltered = baseFiltered.filter(
        (f) =>
          (f.agent_name && f.agent_name.toLowerCase().includes(searchLower)) ||
          (f.feedback && f.feedback.toLowerCase().includes(searchLower)) ||
          (f.lesson && f.lesson.toLowerCase().includes(searchLower))
      );
    }
    const uniqueAgents = new Set(baseFiltered.map((f) => f.agent_name).filter(Boolean));
    return {
      total_feedback: baseFiltered.length,
      approved_feedback: baseFiltered.filter((f) => f.status === "approve").length,
      pending_feedback: baseFiltered.filter((f) => f.status === "pending" || !f.status).length,
      rejected_feedback: baseFiltered.filter((f) => f.status === "reject").length,
      agents_with_feedback: uniqueAgents.size,
    };
  }, [feedbacks, searchValue, selectedAgentTypes]);

  // Extract error message helper
  const extractErrorMessage = useCallback((error) => {
    if (!error) return "An unexpected error occurred";
    if (error.response?.data?.detail) return error.response.data.detail;
    if (error.response?.data?.message) return error.response.data.message;
    if (error.message) return error.message;
    return "Failed to connect to server. Please check your network connection.";
  }, []);

  // Load all feedbacks
  const loadFeedbacks = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchData(APIs.GET_ALL_FEEDBACKS);
      setFeedbacks(Array.isArray(data) ? data : []);
    } catch (err) {
      addMessage(extractErrorMessage(err), "error");
      setFeedbacks([]);
    } finally {
      setLoading(false);
    }
  }, [fetchData, addMessage, extractErrorMessage]);

  // Load feedback stats
  const loadStats = useCallback(async () => {
    setLoadingStats(true);
    try {
      const data = await fetchData(APIs.GET_FEEDBACK_STATS);
      setStats({
        total_feedback: data.total_feedback || 0,
        approved_feedback: data.approved_feedback || 0,
        pending_feedback: data.pending_feedback || 0,
        rejected_feedback: data.rejected_feedback || 0,
        agents_with_feedback: data.agents_with_feedback || 0,
      });
    } catch (err) {
      // Silently fail for stats - show zeros
      setStats({
        total_feedback: 0,
        approved_feedback: 0,
        pending_feedback: 0,
        rejected_feedback: 0,
        agents_with_feedback: 0,
      });
    } finally {
      setLoadingStats(false);
    }
  }, [fetchData]);

  // Initial load
  useEffect(() => {
    if (!hasLoadedRef.current) {
      hasLoadedRef.current = true;
      loadFeedbacks();
      loadStats();
    }
  }, [loadFeedbacks, loadStats]);

  // Control popup visibility based on loading state
  useEffect(() => {
    setShowPopup(!loading);
  }, [loading, setShowPopup]);

  // Handle view button click
  const handleViewFeedback = (feedback) => {
    setSelectedFeedback(feedback);
    setShowDetailModal(true);
  };

  // Handle modal close
  const handleCloseModal = () => {
    setShowDetailModal(false);
    setSelectedFeedback(null);
  };

  // Handle status change (approve/reject)
  const handleStatusChange = async (feedback, newStatus) => {
    const oldStatus = feedback.status;

    // Optimistic update
    setFeedbacks((prev) =>
      prev.map((f) =>
        f.response_id === feedback.response_id ? { ...f, status: newStatus } : f
      )
    );

    try {
      await putData(APIs.UPDATE_APPROVAL_RESPONSE, {
        response_id: feedback.response_id,
        status: newStatus,
        lesson: feedback.lesson || "",
      });
      const statusLabel = newStatus === "approve" ? "approved" : newStatus === "reject" ? "rejected" : "set to pending";
      addMessage(`Feedback ${statusLabel} successfully`, "success");
      // Refresh stats
      loadStats();
    } catch (err) {
      // Revert on error
      setFeedbacks((prev) =>
        prev.map((f) =>
          f.response_id === feedback.response_id ? { ...f, status: oldStatus } : f
        )
      );
      addMessage(extractErrorMessage(err), "error");
    }
  };

  // Open zoom popup for feedback content (read-only)
  const handleFeedbackZoomOpen = (feedback) => {
    setFeedbackZoomContent(feedback.feedback || "");
    setShowFeedbackZoom(true);
  };

  // Open zoom popup for learning content
  const handleZoomOpen = (feedback) => {
    setZoomContent(feedback.lesson || "");
    setZoomFeedback(feedback);
    setShowZoomPopup(true);
  };

  // Save from zoom popup
  const handleZoomSave = async (updatedContent) => {
    if (zoomFeedback) {
      try {
        await putData(APIs.UPDATE_APPROVAL_RESPONSE, {
          response_id: zoomFeedback.response_id,
          status: zoomFeedback.status || "pending",
          lesson: updatedContent,
        });
        setFeedbacks((prev) =>
          prev.map((f) =>
            f.response_id === zoomFeedback.response_id ? { ...f, lesson: updatedContent } : f
          )
        );
        addMessage("Lesson updated successfully", "success");
      } catch (err) {
        addMessage(extractErrorMessage(err), "error");
      }
    }
    setShowZoomPopup(false);
    setZoomFeedback(null);
  };

  // Close zoom popup
  const handleZoomClose = () => {
    setShowZoomPopup(false);
    setZoomFeedback(null);
  };

  // Helper to truncate text at 150 chars
  const truncateText = (text, maxLength = 150) => {
    if (!text || text.length <= maxLength) return text;
    return text.substring(0, maxLength) + "...";
  };

  // Stats card data - uses filteredStats to reflect search results
  const statsCards = [
    {
      label: "Total Feedbacks",
      value: filteredStats.total_feedback,
      icon: "list",
      color: "primary",
      filterKey: "all",
    },
    {
      label: "Approved",
      value: filteredStats.approved_feedback,
      icon: "circle-check",
      color: "success",
      filterKey: "approved",
    },
    {
      label: "Pending",
      value: filteredStats.pending_feedback,
      icon: "history-clock",
      color: "warning",
      filterKey: "pending",
    },
    {
      label: "Rejected",
      value: filteredStats.rejected_feedback,
      icon: "fa-circle-xmark",
      color: "danger",
      filterKey: "rejected",
    },
    {
      label: "Agents with Feedback",
      value: filteredStats.agents_with_feedback,
      icon: "fa-robot",
      color: "info",
      filterKey: null, // Not a filter, just info
    },
  ];

  // Handle stat card click for filtering
  const handleStatCardClick = (filterKey) => {
    if (filterKey !== null) {
      setStatFilter(filterKey);
    }
  };

  return (
    <div className={styles.agentLearningContainer}>
      {/* Stats Dashboard - Clickable Filter Cards */}
      <div className={styles.statsSection}>
        <div className={styles.statsGrid}>
          {statsCards.map((stat) => (
            <button
              key={stat.label}
              type="button"
              className={`${styles.statCard} ${styles[stat.color]} ${stat.filterKey !== null && statFilter === stat.filterKey ? styles.active : ""} ${stat.filterKey !== null ? styles.clickable : ""}`}
              onClick={() => handleStatCardClick(stat.filterKey)}
              disabled={stat.filterKey === null}
            >
              <div className={styles.statIcon}>
                <SVGIcons icon={stat.icon} width={18} height={18} />
              </div>
              <div className={styles.statContent}>
                <span className={styles.statValue}>
                  {loadingStats ? "..." : stat.value}
                </span>
                <span className={styles.statLabel}>{stat.label}</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Table Section */}
      <div className={styles.tableContainer}>
        {loading ? (
          <Loader />
        ) : filteredFeedbacks.length === 0 ? (
          <EmptyState
            message={
              searchValue.trim()
                ? "No feedbacks found matching your search."
                : "No feedbacks available."
            }
            icon="fa-inbox"
          />
        ) : (
          <table className={styles.feedbackTable}>
            <thead>
              <tr>
                <th className={styles.thAgentName}>Agent Name</th>
                <th className={styles.thFeedback}>Feedback</th>
                <th className={styles.thLearning}>Learning</th>
                <th className={styles.thApproval}>Actions</th>
                <th className={styles.thStatus}>Status</th>
                <th className={styles.thActions}>View</th>
              </tr>
            </thead>
            <tbody>
              {filteredFeedbacks.map((feedback) => (
                <tr key={feedback.response_id} className={styles.tableRow}>
                  <td className={styles.tdAgentName}>
                    <span
                      className={styles.agentNameText}
                      title={feedback.agent_name || ""}
                    >
                      {feedback.agent_name || "--"}
                    </span>
                  </td>
                  <td className={styles.tdFeedback}>
                    <div className={styles.feedbackCellWrapper}>
                      <div
                        className={styles.feedbackText}
                        title={feedback.feedback || ""}
                      >
                        {feedback.feedback
                          ? (
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {feedback.feedback}
                            </ReactMarkdown>
                          )
                          : "--"}
                      </div>
                      {feedback.feedback && (
                        <div className={styles.feedbackActions}>
                          <button
                            type="button"
                            className={styles.expandIconBtn}
                            onClick={() => handleFeedbackZoomOpen(feedback)}
                            title="View full feedback"
                          >
                            <SVGIcons icon="fa-solid fa-up-right-and-down-left-from-center" width={12} height={12} />
                          </button>
                        </div>
                      )}
                    </div>
                  </td>
                  <td className={styles.tdLearning}>
                    <div className={styles.learningCellWrapper}>
                      <span
                        className={styles.learningText}
                        title={feedback.lesson || ""}
                      >
                        {feedback.lesson
                          ? truncateText(feedback.lesson, 100)
                          : <em className={styles.noLearning}>No lesson</em>}
                      </span>
                      <div className={styles.learningActions}>
                        <button
                          type="button"
                          className={styles.editButton}
                          onClick={() => handleZoomOpen(feedback)}
                          title="Edit lesson"
                        >
                          <SVGIcons icon="pencil" width={14} height={14} />
                        </button>
                      </div>
                    </div>
                  </td>
                  <td className={styles.tdApproval}>
                    <div className={styles.cellCenter}>
                      <div className={styles.actionButtons}>
                        {/* Pending: show both approve and reject buttons */}
                        {(feedback.status === "pending" || !feedback.status) && (
                          <>
                            <button
                              type="button"
                              className={`${styles.actionBtn} ${styles.approveBtn}`}
                              onClick={() => handleStatusChange(feedback, "approve")}
                              title="Approve"
                            >
                              <SVGIcons icon="circle-check" width={16} height={16} />
                            </button>
                            <button
                              type="button"
                              className={`${styles.actionBtn} ${styles.rejectBtn}`}
                              onClick={() => handleStatusChange(feedback, "reject")}
                              title="Reject"
                            >
                              <SVGIcons icon="fa-circle-xmark" width={16} height={16} />
                            </button>
                          </>
                        )}
                        {/* Approved: show reject button to modify */}
                        {feedback.status === "approve" && (
                          <button
                            type="button"
                            className={`${styles.actionBtn} ${styles.rejectBtn}`}
                            onClick={() => handleStatusChange(feedback, "reject")}
                            title="Reject"
                          >
                            <SVGIcons icon="fa-circle-xmark" width={16} height={16} />
                          </button>
                        )}
                        {/* Rejected: show approve button to modify */}
                        {feedback.status === "reject" && (
                          <button
                            type="button"
                            className={`${styles.actionBtn} ${styles.approveBtn}`}
                            onClick={() => handleStatusChange(feedback, "approve")}
                            title="Approve"
                          >
                            <SVGIcons icon="circle-check" width={16} height={16} />
                          </button>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className={styles.tdStatus}>
                    <div className={styles.cellCenter}>
                      <span
                        className={`${styles.statusBadge} ${feedback.status === "approve" ? styles.statusApproved :
                            feedback.status === "reject" ? styles.statusRejected :
                              styles.statusPending
                          }`}
                      >
                        {feedback.status === "approve" ? "Approved" :
                          feedback.status === "reject" ? "Rejected" : "Pending"}
                      </span>
                    </div>
                  </td>
                  <td className={styles.tdActions}>
                    <div className={styles.cellCenter}>
                      <button
                        type="button"
                        className={styles.viewButton}
                        onClick={() => handleViewFeedback(feedback)}
                        title="View full details"
                      >
                        <SVGIcons icon="eye" width={18} height={18} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Detail Modal */}
      {showDetailModal && selectedFeedback && (
        <FeedbackDetailModal
          feedback={selectedFeedback}
          onClose={handleCloseModal}
        />
      )}

      {/* Zoom Popup for Feedback - read-only, markdown rendered */}
      <ZoomPopup
        show={showFeedbackZoom}
        onClose={() => setShowFeedbackZoom(false)}
        title="Feedback"
        content={feedbackZoomContent}
        type="markdown"
        readOnly={true}
        hideFooter={true}
        showCopy={true}
      />

      {/* Zoom Popup for Learning - same as tools expand */}
      <ZoomPopup
        show={showZoomPopup}
        onClose={handleZoomClose}
        title="Learning - Lesson"
        content={zoomContent}
        onSave={handleZoomSave}
        type="text"
        readOnly={false}
        showCopy={true}
      />
    </div>
  );
};

export default AgentLearning;
