import React, { useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faTimes,
  faThumbsDown,
  faPaperPlane
} from "@fortawesome/free-solid-svg-icons";
import styles from "./FeedbackModal.module.css";

const FeedbackModal = ({ messageId, onSubmit, onClose }) => {
  const [feedback, setFeedback] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!feedback.trim()) return;

    setIsSubmitting(true);
    try {
      await onSubmit(messageId, feedback, 'negative');
    } catch (error) {
      console.error("Error submitting feedback:", error);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  return (
    <div className={styles.overlay} onClick={handleOverlayClick}>
      <div className={styles.modal}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <FontAwesomeIcon icon={faThumbsDown} className={styles.headerIcon} />
            <h3 className={styles.title}>Provide Feedback</h3>
          </div>
          <button className={styles.closeButton} onClick={onClose}>
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>

        {/* Content */}
        <div className={styles.content}>
          <p className={styles.description}>
            We're sorry the response didn't meet your expectations. 
            Your feedback helps us improve our AI responses.
          </p>

          <form onSubmit={handleSubmit} className={styles.form}>
            <div className={styles.inputGroup}>
              <label htmlFor="feedback" className={styles.label}>
                What went wrong with this response?
              </label>
              <textarea
                id="feedback"
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder="Please describe what you expected vs what you received, or any specific issues with the response..."
                className={styles.textarea}
                rows={4}
                maxLength={1000}
                required
              />
              <div className={styles.charCount}>
                {feedback.length}/1000
              </div>
            </div>

            {/* Predefined options */}
            <div className={styles.quickOptions}>
              <span className={styles.quickOptionsLabel}>Quick feedback:</span>
              <div className={styles.optionsGrid}>
                {[
                  "Response was inaccurate",
                  "Response was incomplete",
                  "Response was irrelevant",
                  "Response was unclear",
                  "Response was too long",
                  "Response was inappropriate"
                ].map((option) => (
                  <button
                    key={option}
                    type="button"
                    className={styles.quickOption}
                    onClick={() => setFeedback(option)}
                  >
                    {option}
                  </button>
                ))}
              </div>
            </div>

            {/* Footer */}
            <div className={styles.footer}>
              <button
                type="button"
                className={styles.cancelButton}
                onClick={onClose}
                disabled={isSubmitting}
              >
                Cancel
              </button>
              <button
                type="submit"
                className={styles.submitButton}
                disabled={!feedback.trim() || isSubmitting}
              >
                {isSubmitting ? (
                  <>
                    <span className={styles.spinner}></span>
                    Submitting...
                  </>
                ) : (
                  <>
                    <FontAwesomeIcon icon={faPaperPlane} />
                    Submit Feedback
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
};

export default FeedbackModal;
