import { useState, useEffect } from "react";
import styles from "./PlanVerifier.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import TextareaWithActions from "../commonComponents/TextareaWithActions";

/**
 * PlanVerifier Component
 * Displays the proposed plan with steps in Figma design style
 * Includes approve/reject functionality and feedback form
 */
const PlanVerifier = ({ plan = [], onApprove, onRequestChanges, onSubmitFeedback, onCancelFeedback, isProcessing = false, isApproved = false, executionSteps = [], showButtons = true }) => {
  const [showFeedbackForm, setShowFeedbackForm] = useState(false);
  const [feedbackText, setFeedbackText] = useState("");
  const [expandedSteps, setExpandedSteps] = useState({});
  // Track if user has clicked a button to prevent double-click showing buttons again
  const [hasClickedAction, setHasClickedAction] = useState(false);
  // State to control expand/collapse of the plan section
  const [isExpanded, setIsExpanded] = useState(true);

  // Reset hasClickedAction when a new plan comes in (plan content changes)
  useEffect(() => {
    setHasClickedAction(false);
    setShowFeedbackForm(false);
    setIsExpanded(true); // Auto-expand when new plan arrives
  }, [JSON.stringify(plan)]);

  const toggleExpanded = () => {
    setIsExpanded(!isExpanded);
  };

  const handleApprove = () => {
    setHasClickedAction(true);
    if (onApprove) {
      onApprove();
    }
  };

  const handleRequestChanges = () => {
    setHasClickedAction(true);
    setShowFeedbackForm(true);
    // Call onRequestChanges to hit the endpoint when clicking Request Changes
    if (onRequestChanges) {
      onRequestChanges();
    }
  };

  const handleSubmitFeedback = () => {
    if (onSubmitFeedback && feedbackText.trim()) {
      onSubmitFeedback(feedbackText);
      setFeedbackText("");
      setShowFeedbackForm(false);
    }
  };

  const handleCancel = () => {
    setFeedbackText("");
    setShowFeedbackForm(false);
    if (onCancelFeedback) {
      onCancelFeedback();
    }
  };

  const toggleStep = (index) => {
    setExpandedSteps((prev) => ({
      ...prev,
      [index]: !prev[index],
    }));
  };

  if (!plan || plan.length === 0) {
    return null;
  }

  return (
    <div className={styles.planVerifierContainer}>
      {/* Header - Clickable to expand/collapse */}
      <div className={`${styles.planHeader} ${!isExpanded ? styles.collapsed : ""}`} onClick={toggleExpanded}>
        <div className={styles.headerLeft}>
          <div className={styles.headerIcon}>
            <SVGIcons icon="plan-header-icon" width={20} height={20} stroke="#0073CF" />
          </div>
          <span className={styles.headerTitle}>{isApproved ? "Proposed Plan - Approved" : "Proposed Plan - Awaiting Approval"}</span>
        </div>
        <SVGIcons
          icon="chevron-down-sm"
          width={16}
          height={16}
          color="currentColor"
          stroke="currentColor"
          style={{ transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s ease" }}
        />
      </div>

      {/* Collapsible Content */}
      {isExpanded && (
        <>
          {/* Plan Content */}
          <div className={styles.planContent}>
            <p className={styles.planDescription}>I plan to complete your request in {plan.length} steps:</p>

            {/* Plan Steps */}
            <div className={styles.planSteps}>
              {plan.map((step, index) => {
                // Strip "STEP X:" prefix if present
                const cleanedStep = typeof step === "string" ? step.replace(/^STEP\s*\d+\s*:\s*/i, "").trim() : step;
                return (
                  <div key={`plan-step-${index}`} className={styles.planStep}>
                    <div className={styles.stepNumber}>{index + 1}</div>
                    <span className={styles.stepText}>{cleanedStep}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Execution Progress Steps */}
          {isApproved && executionSteps.length > 0 && (
            <div className={styles.executionProgress}>
              {executionSteps.map((execStep, index) => (
                <div key={`exec-step-${index}`} className={styles.executionStep}>
                  <div className={`${styles.executionIcon} ${execStep.status === "completed" ? styles.completed : execStep.status === "in-progress" ? styles.inProgress : ""}`}>
                    {execStep.status === "completed" ? (
                      <SVGIcons icon="step-completed" width={14} height={14} fill="#2196F3" stroke="white" />
                    ) : execStep.status === "in-progress" ? (
                      <span className={styles.spinnerIcon}>
                        <SVGIcons icon="step-spinner" width={14} height={14} stroke="#2196F3" />
                      </span>
                    ) : (
                      <div className={styles.pendingDot}></div>
                    )}
                  </div>
                  <span className={`${styles.executionStepText} ${execStep.status === "pending" ? styles.pending : ""}`}>{execStep.name}</span>
                </div>
              ))}
            </div>
          )}

          {/* Feedback Form */}
          {showFeedbackForm && (
            <div className={styles.feedbackSection}>
              <p className={styles.feedbackLabel}>How should I adjust this plan?</p>
              <TextareaWithActions
                name="feedbackText"
                placeholder="Describe The Changes You'd Like Me To Make..."
                value={feedbackText}
                onChange={(e) => setFeedbackText(e.target.value)}
                rows={3}
                showCopy={false}
                showExpand={false}
              />
              <div className={styles.feedbackButtons}>
                <button className={styles.submitFeedbackBtn} onClick={handleSubmitFeedback} disabled={!feedbackText.trim() || isProcessing}>
                  Submit Feedback
                </button>
              </div>
            </div>
          )}

          {/* Action Buttons - Show when not approved, not in feedback form, showButtons is true, and user hasn't clicked yet */}
          {!isApproved && !showFeedbackForm && showButtons && !hasClickedAction && (
            <div className={styles.actionButtons}>
              <button className={styles.approveBtn} onClick={handleApprove} disabled={isProcessing}>
                <SVGIcons icon="thumbs-up" width={15} height={15} stroke="white" />
                Approve
              </button>
              <button className={styles.requestChangesBtn} onClick={handleRequestChanges} disabled={isProcessing}>
                <SVGIcons icon="thumbs-down" width={15} height={15} stroke="#1A1A1A" />
                Request Changes
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default PlanVerifier;
