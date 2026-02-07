import { useState, useRef, useEffect } from "react";
import styles from "./ResponseDetail.module.css";
import SVGIcons from "../../Icons/SVGIcons";

// ResponseDetail component
const ResponseDetail = ({ form, onChange, onSubmit, onBack }) => {
  const [isLessonEditable, setIsLessonEditable] = useState(false);
  const [isApprovedModified, setIsApprovedModified] = useState(false);
  const originalLessonRef = useRef(form.lesson);
  const originalApprovedRef = useRef(form.approved);

  // Check if anything has been modified to enable/disable the update button
  const hasChanges = isLessonEditable || isApprovedModified;

  useEffect(() => {
    // Update the original refs when form changes from parent
    if (!isLessonEditable) {
      originalLessonRef.current = form.lesson;
    }
    if (!isApprovedModified) {
      originalApprovedRef.current = form.approved;
    }
  }, [form.lesson, form.approved, isLessonEditable, isApprovedModified]);

  const handleEditClick = () => {
    // Store the original value when starting to edit
    originalLessonRef.current = form.lesson;
    setIsLessonEditable(true);
  };

  const handleCancelEdit = () => {
    // Revert to original value and disable editing
    const event = {
      target: {
        name: "lesson",
        value: originalLessonRef.current,
      },
    };
    onChange(event);
    setIsLessonEditable(false);
  };

  const handleApprovedToggle = () => {
    const newValue = !form.approved;
    const event = {
      target: {
        name: "approved",
        value: newValue,
      },
    };
    onChange(event);

    // Check if the new value is different from the original
    setIsApprovedModified(newValue !== originalApprovedRef.current);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    // Only allow submission if there are changes
    if (hasChanges) {
      await onSubmit(e);
      setIsLessonEditable(false); // Reset edit state after submission
      setIsApprovedModified(false); // Reset approved modification state
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.headerActions}>
        <h2 className={styles.heading}>Edit Response</h2>
        <button type="button" onClick={onBack} className={styles.backButton}>
          Back to Responses
        </button>
      </div>
      <div className={styles.responseDetailContent}>
        <div className={styles.responseDetailHeader}>
          <p>
            <strong> Agent Name:</strong> <span className={styles.infoLabel} >{form.agent_name || "--"}</span>
          </p>
          <p>
            <strong> Response Name:</strong> <span className={styles.infoLabel} >{form.feedback || "--"}</span>
          </p>
        </div>
        <form onSubmit={handleSubmit} className={styles.form}>
          <input type="hidden" name="response_id" value={form.response_id} />

          <div className={styles.fieldGroup}>
            <div className={styles.fieldGroupTitle}>Original Query</div>
            <label className={styles.label}>Query:</label>
            <textarea name="query" value={form.query} onChange={onChange} className={styles.textarea} disabled />
          </div>

          <div className={styles.fieldGroup}>
            <div className={styles.fieldGroupTitle}>Original Response</div>
            <label className={styles.label}>Old Final Response:</label>
            <textarea name="old_final_response" value={form.old_final_response} onChange={onChange} className={styles.textarea} disabled />
            <label className={styles.label}>Old Steps:</label>
            <textarea name="old_steps" value={form.old_steps} onChange={onChange} className={styles.textarea} disabled />
          </div>

          <div className={styles.fieldGroup}>
            <div className={styles.fieldGroupTitle}>Feedback and Updates</div>
            <label className={styles.label}>Feedback:</label>
            <textarea name="feedback" value={form.feedback} onChange={onChange} className={styles.textarea} disabled />
            <label className={styles.label}>New Final Response:</label>
            <textarea name="new_final_response" value={form.new_final_response} onChange={onChange} className={styles.textarea} disabled />
            <label className={styles.label}>New Steps:</label>
            <textarea name="new_steps" value={form.new_steps} onChange={onChange} className={styles.textarea} disabled />
          </div>

          <div className={styles.fieldGroup}>
            <div className={styles.fieldGroupTitle}>
              Lesson
              {!isLessonEditable && (
                <button type="button" onClick={handleEditClick} className={styles.editButton} title="Edit lesson">
                  <SVGIcons icon="pencil" width={16} height={16} />
                </button>
              )}
              {isLessonEditable && (
                <button type="button" onClick={handleCancelEdit} className={styles.cancelButton} title="Cancel editing">
                  <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
                    <path d="M15 5L5 15M5 5l10 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              )}
            </div>
            <textarea
              name="lesson"
              value={form.lesson}
              onChange={onChange}
              className={styles.textarea}
              disabled={!isLessonEditable}
              style={{
                backgroundColor: isLessonEditable ? "white" : "#f5f5f5",
                cursor: isLessonEditable ? "text" : "not-allowed",
              }}
            />
          </div>

          <div className={styles.fieldGroup}>
            <div className={styles.fieldGroupTitle}>Learning Status</div>
            <div style={{ display: "flex", alignItems: "center", gap: "12px", marginTop: "8px" }}>
              <span
                style={{
                  fontSize: "14px",
                  color: form.approved ? "#666" : "#333",
                  fontWeight: form.approved ? "normal" : "600",
                }}>
                Excluded from Learning
              </span>

              <div
                onClick={handleApprovedToggle}
                style={{
                  width: "48px",
                  height: "24px",
                  backgroundColor: form.approved ? "#0078d4" : "#e0e0e0",
                  borderRadius: "12px",
                  position: "relative",
                  cursor: "pointer",
                  transition: "all 0.3s ease",
                  border: "1px solid " + (form.approved ? "#0078d4" : "#ccc"),
                }}
                title={form.approved ? "Included in Learning" : "Excluded from Learning"}>
                <div
                  style={{
                    width: "20px",
                    height: "20px",
                    backgroundColor: "white",
                    borderRadius: "50%",
                    position: "absolute",
                    top: "1px",
                    left: form.approved ? "26px" : "1px",
                    transition: "all 0.3s ease",
                    boxShadow: "0 2px 4px rgba(0,0,0,0.2)",
                  }}
                />
              </div>

              <span
                style={{
                  fontSize: "14px",
                  color: form.approved ? "#333" : "#666",
                  fontWeight: form.approved ? "600" : "normal",
                }}>
                Included in Learning
              </span>
            </div>

            {isApprovedModified && (
              <div
                style={{
                  fontSize: "12px",
                  color: "#ff9800",
                  marginTop: "4px",
                  fontStyle: "italic",
                }}>
                Learning status modified
              </div>
            )}
          </div>

          <div className={styles.buttonRow}>
            <button
              type="submit"
              className={styles.submitButton}
              disabled={!hasChanges}
              style={{
                opacity: hasChanges ? 1 : 0.5,
                cursor: hasChanges ? "pointer" : "not-allowed",
              }}>
              Update Response
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default ResponseDetail;
