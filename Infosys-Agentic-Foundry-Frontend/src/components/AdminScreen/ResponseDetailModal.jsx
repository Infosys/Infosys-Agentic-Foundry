import { useState, useRef, useEffect } from "react";
import styles from "./ResponseDetail.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import Button from "../../iafComponents/GlobalComponents/Buttons/Button";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";
import TextareaWithActions from "../commonComponents/TextareaWithActions";

/**
 * ResponseDetailModal - Modal overlay component for editing response details
 * Now uses the reusable FullModal component for consistency across the app.
 */
const ResponseDetailModal = ({ isOpen, onClose, form, onChange, onSubmit, loading }) => {
  const [isLessonEditable, setIsLessonEditable] = useState(false);
  const [isStatusModified, setIsStatusModified] = useState(false);
  const originalLessonRef = useRef(form?.lesson);
  const originalStatusRef = useRef(form?.status);

  // Check if anything has been modified to enable/disable the update button
  const hasChanges = isLessonEditable || isStatusModified;

  useEffect(() => {
    // Update the original refs when form changes from parent
    if (!isLessonEditable) {
      originalLessonRef.current = form?.lesson;
    }
    if (!isStatusModified) {
      originalStatusRef.current = form?.status;
    }
  }, [form?.lesson, form?.status, isLessonEditable, isStatusModified]);

  // Reset edit states when modal opens with new data
  useEffect(() => {
    if (isOpen) {
      setIsLessonEditable(false);
      setIsStatusModified(false);
      originalLessonRef.current = form?.lesson;
      originalStatusRef.current = form?.status;
    }
  }, [isOpen, form?.response_id]);

  const handleEditClick = () => {
    originalLessonRef.current = form?.lesson;
    setIsLessonEditable(true);
  };

  const handleCancelEdit = () => {
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
    // Not used for 3-state; keeping for backwards compat
  };

  const handleStatusSelect = (newStatus) => {
    const event = {
      target: {
        name: "status",
        value: newStatus,
      },
    };
    onChange(event);
    setIsStatusModified(newStatus !== originalStatusRef.current);
  };

  const handleSubmit = async (e) => {
    if (e) e.preventDefault();
    if (hasChanges) {
      await onSubmit(e);
      setIsLessonEditable(false);
      setIsStatusModified(false);
    }
  };

  const handleClose = () => {
    setIsLessonEditable(false);
    setIsStatusModified(false);
    onClose();
  };

  // Footer buttons
  const renderFooter = () => (
    <div style={{ display: "flex", gap: "12px" }}>
      <Button type="secondary" onClick={handleClose} htmlType="button">
        Cancel
      </Button>
      <Button type="primary" onClick={handleSubmit} htmlType="button" disabled={!hasChanges}>
        Update Response
      </Button>
    </div>
  );

  return (
    <FullModal
      isOpen={isOpen}
      onClose={handleClose}
      title="Edit Response"
      loading={loading}
      headerInfo={[{ label: "Agent", value: form?.agent_name || "--" }]}
      footer={renderFooter()}>
      <form onSubmit={handleSubmit} className="form-section">
        <div className="formContent">
          <div className="form">
            {/* Response Name Info */}
            <div className={styles.responseInfoBar}>
              <span className={styles.responseInfoLabel}>Response:</span>
              <span className={styles.responseInfoValue}>{form?.feedback || "--"}</span>
            </div>

            {/* Original Query */}
            <div className="formGroup">
              <TextareaWithActions name="query" value={form?.query || ""} onChange={onChange} label="Original Query" disabled={true} rows={3} readOnly={true} />
            </div>
            <div className="responseDetailGroup">
              <p className={`label-desc ${styles.responseDetailGroupHeader}`}>Original Response</p>
              <div className="gridTwoCol">
                {/* Old Final Response */}
                <div className="formGroup">
                  <TextareaWithActions
                    name="old_final_response"
                    value={form?.old_final_response || ""}
                    onChange={onChange}
                    label="Old Final Response"
                    disabled={true}
                    rows={4}
                    readOnly={true}
                  />
                </div>

                {/* Old Steps */}
                <div className="formGroup">
                  <TextareaWithActions name="old_steps" value={form?.old_steps || ""} onChange={onChange} label="Old Steps" disabled={true} rows={4} readOnly={true} />
                </div>
              </div>
            </div>
            <div className="responseDetailGroup">
              <p className={`label-desc ${styles.responseDetailGroupHeader}`}>Feedback and Updates</p>
              <div className="gridThreeCol">
                {/* Feedback */}
                <div className="formGroup">
                  <TextareaWithActions name="feedback" value={form?.feedback || ""} onChange={onChange} label="Feedback" disabled={true} rows={4} readOnly={true} />
                </div>

                {/* New Final Response */}
                <div className="formGroup">
                  <TextareaWithActions
                    name="new_final_response"
                    value={form?.new_final_response || ""}
                    onChange={onChange}
                    label="New Final Response"
                    disabled={true}
                    rows={4}
                    readOnly={true}
                  />
                </div>

                {/* New Steps */}
                <div className="formGroup">
                  <TextareaWithActions name="new_steps" value={form?.new_steps || ""} onChange={onChange} label="New Steps" disabled={true} rows={4} readOnly={true} />
                </div>
              </div>
            </div>
            {/* Lesson (Editable) */}
            <div className="formGroup">
              <div className={styles.lessonHeader}>
                <span className="label-desc">Lesson</span>
                {!isLessonEditable ? (
                  <button type="button" onClick={handleEditClick} className={styles.editIconBtn} title="Edit lesson">
                    <SVGIcons icon="pencil" width={16} height={16} />
                  </button>
                ) : (
                  <button type="button" onClick={handleCancelEdit} className={styles.cancelIconBtn} title="Cancel editing">
                    <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
                      <path d="M15 5L5 15M5 5l10 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                )}
              </div>
              <TextareaWithActions
                name="lesson"
                value={form?.lesson || ""}
                onChange={onChange}
                disabled={!isLessonEditable}
                rows={4}
                readOnly={!isLessonEditable}
                showCopy={true}
                showExpand={true}
                className={!isLessonEditable ? styles.lessonTextareaDisabled : styles.lessonTextareaEditable}
              />
            </div>

            {/* Learning Status - 3 State Buttons */}
            <div className="formGroup">
              <label className={`label-desc ${styles.responseDetailGroupHeader}`}>Learning Status</label>
              <div className={styles.statusButtonGroup}>
                <button
                  type="button"
                  className={`${styles.statusBtn} ${styles.statusBtnApprove} ${form?.status === "approve" ? styles.statusBtnActive : ""}`}
                  onClick={() => handleStatusSelect("approve")}
                  disabled={form?.status === "approve"}>
                  <SVGIcons icon="check" width={14} height={14} />
                  Approve
                </button>
                <button
                  type="button"
                  className={`${styles.statusBtn} ${styles.statusBtnReject} ${form?.status === "reject" ? styles.statusBtnActive : ""}`}
                  onClick={() => handleStatusSelect("reject")}
                  disabled={form?.status === "reject"}>
                  <SVGIcons icon="close" width={14} height={14} />
                  Reject
                </button>
                <button
                  type="button"
                  className={`${styles.statusBtn} ${styles.statusBtnPending} ${form?.status === "pending" ? styles.statusBtnActive : ""}`}
                  onClick={() => handleStatusSelect("pending")}
                  disabled={form?.status === "pending"}>
                  <SVGIcons icon="history-clock" width={14} height={14} />
                  Pending
                </button>
              </div>
              {isStatusModified && <div className={styles.modifiedIndicator}>Learning status modified</div>}
            </div>
          </div>
        </div>
      </form>
    </FullModal>
  );
};

export default ResponseDetailModal;
