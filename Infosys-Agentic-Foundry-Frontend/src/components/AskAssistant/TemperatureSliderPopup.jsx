import React from "react";
import styles from "./TemperatureSlider.module.css";

const TemperatureSliderPopup = ({ value, onChange, onClose, hideOverlay, disabled }) => {
  const safeValue = typeof value === "number" && !Number.isNaN(value) ? value : 0;
  const clampedValue = Math.min(1, Math.max(0, safeValue));
  const displayValue = clampedValue.toFixed(1);

  const handleSliderChange = (e) => {
    const next = Number(e.target.value);
    if (!Number.isNaN(next)) {
      onChange(Math.min(1, Math.max(0, next)));
    }
  };

  const innerContent = (
    <div className={styles.temperatureContainer}>
      <div className={styles.tempHeader}>
        <span className={styles.tempTitle}>Temperature</span>
        <span className={styles.tempValue} style={disabled ? { color: "#9CA3AF" } : undefined}>
          {displayValue}
        </span>
      </div>

      <div className={styles.rangeWrapper}>
        <input
          type="range"
          min={0}
          max={1}
          step={0.1}
          value={clampedValue}
          onChange={handleSliderChange}
          className={styles.sliderInput}
          disabled={disabled}
          aria-label="Temperature slider"
          style={{
            "--progress": `${Math.round(clampedValue * 100)}%`,
          }}
        />
      </div>

      <div className={styles.sliderRow}>
        <span className={styles.preciseLabel}>Precise</span>
        <span className={styles.creativeLabel}>Creative</span>
      </div>
    </div>
  );
  if (hideOverlay) {
    // When used inside an existing dropdown card, just render the inner layout
    return innerContent;
  }

  const content = <div className={styles.popupContent}>{innerContent}</div>;

  return <div className={styles.popupOverlay}>{content}</div>;
};

export default TemperatureSliderPopup;
