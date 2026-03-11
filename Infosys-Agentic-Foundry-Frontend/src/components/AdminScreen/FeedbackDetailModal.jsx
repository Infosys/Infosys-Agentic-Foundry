import React from "react";
import styles from "./FeedbackDetailModal.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import Button from "../../iafComponents/GlobalComponents/Buttons/Button";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";
import TextareaWithActions from "../commonComponents/TextareaWithActions";

/**
 * FeedbackDetailModal - Read-only modal for viewing full feedback details
 * Shows all feedback data fields in a clean, organized layout
 * 
 * @param {Object} feedback - The feedback data object
 * @param {Function} onClose - Callback to close the modal
 */
const FeedbackDetailModal = ({ feedback, onClose }) => {
  if (!feedback) return null;

  // Footer with close button only
  const renderFooter = () => (
    <div style={{ display: "flex", gap: "12px" }}>
      <Button type="primary" onClick={onClose} htmlType="button">
        Close
      </Button>
    </div>
  );

  // Header info chips
  const headerInfo = [
    { label: "Agent", value: feedback.agent_name || "--" },
    {
      label: "Status",
      value: feedback.approved ? "Approved" : "Pending",
      className: feedback.approved ? styles.statusApproved : styles.statusPending
    },
  ];

  return (
    <FullModal
      isOpen={true}
      onClose={onClose}
      title="Feedback Details"
      loading={false}
      headerInfo={headerInfo}
    >
      <div className={styles.detailContent}>
        {/* Response ID and Agent Info */}
        <div className={styles.infoBar}>
          <div className={styles.infoItem}>
            <span className={styles.infoLabel}>Response ID:</span>
            <span className={styles.infoValue}>{feedback.response_id || "--"}</span>
          </div>
          <div className={styles.infoItem}>
            <span className={styles.infoLabel}>Agent:</span>
            <span className={styles.infoValue}>{feedback.agent_name || "--"}</span>
          </div>
        </div>

        {/* Original Query Section */}
        <div className={styles.section}>
          <h3 className={styles.sectionTitle}>
            <SVGIcons icon="messages-square" width={18} height={18} />
            Original Query
          </h3>
          <div className={styles.fieldReadOnly}>
            <TextareaWithActions
              name="query"
              value={feedback.query || "No query available"}
              disabled={true}
              rows={3}
              readOnly={true}
              showCopy={true}
            />
          </div>
        </div>

        {/* Original Response Section */}
        <div className={styles.section}>
          <h3 className={styles.sectionTitle}>
            <SVGIcons icon="fileText" width={18} height={18} />
            Original Response
          </h3>
          <div className={styles.gridTwoCol}>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Old Final Response</label>
              <TextareaWithActions
                name="old_final_response"
                value={feedback.old_final_response || "N/A"}
                disabled={true}
                rows={4}
                readOnly={true}
                showCopy={true}
                showExpand={true}
              />
            </div>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Old Steps</label>
              <TextareaWithActions
                name="old_steps"
                value={feedback.old_steps || "N/A"}
                disabled={true}
                rows={4}
                readOnly={true}
                showCopy={true}
                showExpand={true}
              />
            </div>
          </div>
        </div>

        {/* Feedback and Updates Section */}
        <div className={styles.section}>
          <h3 className={styles.sectionTitle}>
            <SVGIcons icon="pencil" width={18} height={18} />
            Feedback & Updates
          </h3>
          <div className={styles.gridThreeCol}>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Feedback</label>
              <TextareaWithActions
                name="feedback"
                value={feedback.feedback || "No feedback provided"}
                disabled={true}
                rows={4}
                readOnly={true}
                showCopy={true}
                showExpand={true}
              />
            </div>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>New Final Response</label>
              <TextareaWithActions
                name="new_final_response"
                value={feedback.new_final_response || "N/A"}
                disabled={true}
                rows={4}
                readOnly={true}
                showCopy={true}
                showExpand={true}
              />
            </div>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>New Steps</label>
              <TextareaWithActions
                name="new_steps"
                value={feedback.new_steps || "N/A"}
                disabled={true}
                rows={4}
                readOnly={true}
                showCopy={true}
                showExpand={true}
              />
            </div>
          </div>
        </div>

        {/* Learning Section */}
        <div className={styles.section}>
          <h3 className={styles.sectionTitle}>
            <SVGIcons icon="brain" width={18} height={18} />
            Learning
          </h3>
          <div className={styles.fieldGroup}>
            <label className={styles.fieldLabel}>Lesson Learned</label>
            <TextareaWithActions
              name="lesson"
              value={feedback.lesson || "No lesson captured"}
              disabled={true}
              rows={4}
              readOnly={true}
              showCopy={true}
              showExpand={true}
            />
          </div>
        </div>

        {/* Status Section */}
        <div className={styles.section}>
          <h3 className={styles.sectionTitle}>
            <SVGIcons icon="circle-check" width={18} height={18} />
            Approval Status
          </h3>
          <div className={styles.statusDisplay}>
            <span className={`${styles.statusBadgeLarge} ${feedback.approved ? styles.statusApproved : styles.statusPending}`}>
              {feedback.approved ? (
                <>
                  <SVGIcons icon="check" width={16} height={16} />
                  Approved
                </>
              ) : (
                <>
                  <SVGIcons icon="history-clock" width={16} height={16} />
                  Pending Approval
                </>
              )}
            </span>
            <p className={styles.statusHint}>
              {feedback.approved
                ? "This feedback has been approved and included in agent learning."
                : "This feedback is pending review and not yet included in agent learning."}
            </p>
          </div>
        </div>
      </div>
    </FullModal>
  );
};

export default FeedbackDetailModal;
