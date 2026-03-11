import React from "react";
import styles from "./InferenceConfigSliders.module.css";

/**
 * InferenceConfigSliders Component
 *
 * Renders a pair of sliders for inference configuration,
 * styled to match TemperatureSliderPopup design:
 * - Score Threshold (float 0.0-1.0, default 0.7, step 0.1)
 * - Max Epochs (int 1-5, default 3, step 1)
 *
 * Props:
 * @param {string} title - Section title (e.g., "Critic Settings", "Evaluation Settings")
 * @param {number} scoreValue - Current score threshold value (0.0-1.0)
 * @param {function} onScoreChange - Handler for score threshold changes
 * @param {number} epochsValue - Current max epochs value (1-5)
 * @param {function} onEpochsChange - Handler for max epochs changes
 * @param {boolean} disabled - Whether sliders are disabled
 */
const InferenceConfigSliders = ({ title, scoreValue, onScoreChange, epochsValue, onEpochsChange, disabled = false }) => {
  // Calculate progress percentage for slider fill styling (matching TemperatureSlider pattern)
  const scoreProgress = Math.round(((scoreValue - 0) / (1 - 0)) * 100);
  const epochsProgress = Math.round(((epochsValue - 1) / (5 - 1)) * 100);

  return (
    <div className={styles.slidersContainer}>
      {/* Section Title */}
      <div className={styles.sectionHeader}>{title}</div>

      {/* Score Threshold Slider - matches temperatureContainer layout */}
      <div className={styles.sliderGroup}>
        <div className={styles.sliderHeader}>
          <span className={styles.sliderLabel}>Score Threshold</span>
          <span className={styles.sliderValue}>{scoreValue.toFixed(1)}</span>
        </div>
        <div className={styles.rangeWrapper}>
          <input
            type="range"
            min={0}
            max={1}
            step={0.1}
            value={scoreValue}
            onChange={(e) => onScoreChange(parseFloat(e.target.value))}
            className={styles.sliderInput}
            style={{ "--progress": `${scoreProgress}%` }}
            disabled={disabled}
            aria-label={`${title} Score Threshold`}
          />
        </div>
        <div className={styles.sliderRow}>
          <span className={styles.rangeLabel}>Low</span>
          <span className={styles.rangeLabel}>High</span>
        </div>
      </div>

      {/* Max Epochs Slider - matches temperatureContainer layout */}
      <div className={styles.sliderGroup}>
        <div className={styles.sliderHeader}>
          <span className={styles.sliderLabel}>Max Epochs</span>
          <span className={styles.sliderValue}>{epochsValue}</span>
        </div>
        <div className={styles.rangeWrapper}>
          <input
            type="range"
            min={1}
            max={5}
            step={1}
            value={epochsValue}
            onChange={(e) => onEpochsChange(parseInt(e.target.value, 10))}
            className={styles.sliderInput}
            style={{ "--progress": `${epochsProgress}%` }}
            disabled={disabled}
            aria-label={`${title} Max Epochs`}
          />
        </div>
        <div className={styles.sliderRow}>
          <span className={styles.rangeLabel}>1</span>
          <span className={styles.rangeLabel}>5</span>
        </div>
      </div>
    </div>
  );
};

export default InferenceConfigSliders;
