// ResponsesList component - Table format
import { useState } from "react";
import styles from "./ResponseList.module.css";
import SVGIcons from "../../Icons/SVGIcons.js";
import Loader from "../commonComponents/Loader.jsx";
import Toggle from "../commonComponents/Toggle";
import EmptyState from "../commonComponents/EmptyState";

const ResponsesList = ({
  responses,
  onSelect,
  onBack,
  agentName,
  loading = false,
  approvalFilter = "all",
  onApprovalFilterChange,
  onApprovalToggle,
  onLessonChange,
  approvalCounts = { total: 0, approved: 0, nonApproved: 0 }
}) => {
  // Track which lesson is being edited
  const [editingLessonId, setEditingLessonId] = useState(null);
  const [editingLessonValue, setEditingLessonValue] = useState("");
  // Ensure responses is always an array
  const safeResponses = Array.isArray(responses) ? responses : [];

  // Fallback: Extract agent name from first response if agentName prop is missing
  const displayAgentName = agentName || (safeResponses.length > 0 && safeResponses[0]?.agent_name) || "--";

  // Filter options for approval status with counts
  const filterOptions = [
    { value: "all", label: `All (${approvalCounts.total})` },
    { value: "approved", label: `Approved (${approvalCounts.approved})` },
    { value: "non-approved", label: `Non-Approved (${approvalCounts.nonApproved})` },
  ];

  // Start editing a lesson
  const handleStartEditLesson = (response) => {
    setEditingLessonId(response.response_id);
    setEditingLessonValue(response.lesson || "");
  };

  // Save lesson edit
  const handleSaveLesson = (response) => {
    if (onLessonChange) {
      onLessonChange(response, editingLessonValue);
    }
    setEditingLessonId(null);
    setEditingLessonValue("");
  };

  // Cancel lesson edit
  const handleCancelLesson = () => {
    setEditingLessonId(null);
    setEditingLessonValue("");
  };

  return (
    <>
      <div className={styles.headerActions}>
        <button type="button" className="backButton" onClick={onBack} title="Go back">
          <SVGIcons icon="chevron-left" width={20} height={20} color="#6B7280" />
        </button>
        <h2 className={styles.heading}>{displayAgentName || "--"}</h2>

        {/* Approval Filter */}
        {onApprovalFilterChange && (
          <div className={styles.filterContainer}>
            {filterOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`${styles.filterButton} ${approvalFilter === option.value ? styles.filterButtonActive : ""}`}
                onClick={() => onApprovalFilterChange(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className={styles.tableContainer}>
        {loading ? (
          <Loader />
        ) : safeResponses.length === 0 ? (
          <EmptyState message="No responses available for this agent." icon="fa-inbox" />
        ) : (
          <table className={styles.responsesTable}>
            <thead>
              <tr>
                <th className={styles.thFeedback}>Feedback</th>
                <th className={styles.thLesson}>Lesson <span className={styles.editHint}>[Click to edit]</span></th>
                <th className={styles.thStatus}>Status</th>
                <th className={styles.thActions}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {safeResponses.map((response) => (
                <tr key={response.response_id} className={styles.tableRow}>
                  <td className={styles.tdFeedback}>
                    <span className={styles.feedbackText}>
                      {response.feedback || `Response ${response.response_id}`}
                    </span>
                  </td>
                  <td className={styles.tdLesson}>
                    {editingLessonId === response.response_id ? (
                      <div className={styles.lessonEditContainer}>
                        <textarea
                          className={styles.lessonInput}
                          value={editingLessonValue}
                          onChange={(e) => setEditingLessonValue(e.target.value)}
                          placeholder="Enter lesson..."
                          autoFocus
                          rows={3}
                        />
                        <div className={styles.lessonEditActions}>
                          <button
                            type="button"
                            className={styles.lessonSaveBtn}
                            onClick={() => handleSaveLesson(response)}
                            title="Save"
                          >
                            <SVGIcons icon="check" width={14} height={14} />
                          </button>
                          <button
                            type="button"
                            className={styles.lessonCancelBtn}
                            onClick={handleCancelLesson}
                            title="Cancel"
                          >
                            <SVGIcons icon="close" width={14} height={14} />
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className={styles.lessonDisplay} onClick={() => handleStartEditLesson(response)}>
                        <span className={styles.lessonText}>
                          {response.lesson || <em className={styles.lessonPlaceholder}>Click to add lesson</em>}
                        </span>
                        <SVGIcons icon="edit" width={14} height={14} className={styles.lessonEditIcon} />
                      </div>
                    )}
                  </td>
                  <td className={styles.tdStatus}>
                    <div className={styles.statusCell}>
                      <span className={`${styles.statusTag} ${response.approved ? styles.statusApproved : styles.statusNonApproved}`}>
                        {response.approved ? "Approved" : "Non-Approved"}
                      </span>
                      {onApprovalToggle && (
                        <Toggle
                          value={response.approved}
                          onChange={() => onApprovalToggle(response)}
                        />
                      )}
                    </div>
                  </td>
                  <td className={styles.tdActions}>
                    <button
                      type="button"
                      className={styles.viewButton}
                      onClick={() => onSelect(response.response_id)}
                      title="View details"
                    >
                      <SVGIcons icon="eye" width={18} height={18} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
};

export default ResponsesList;
