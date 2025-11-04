import React from "react";
import styles from "./TemperatureSlider.module.css";
import { useRef } from "react";

const TemperatureSliderPopup = ({ value, onChange, onClose, hideOverlay, disabled }) => {
  const inputRef = useRef();
  const handleInputChange = (e) => {
    let input = e.target.value;
    // Remove leading zeros except for '0.'
    if (/^0[0-9]+/.test(input) && !input.startsWith('0.')) {
      input = input.replace(/^0+/, '');
    }
    let val = parseFloat(input);
    if (isNaN(val)) val = 0;
    if (val < 0) val = 0;
    if (val > 1) val = 1;
    onChange(val);
  };
  const content = (
    <div className={styles.popupContent} style={hideOverlay ? { boxShadow: "none", minWidth: 220, padding: 2 } : {}}>
      <div style={{ width: "100%", display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ fontSize: 13, color: disabled ? "#bdbdbd" : "#222"}}>0</span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.1}
          value={value}
          onChange={e => onChange(Number(e.target.value))}
          className={styles.sliderInput}
          disabled={disabled}
          aria-label="Temperature slider"
          style={{
            flex: 1,
            '--progress': `${Math.round((Number(value) || 0) * 100)}%`
          }}
        />
        <span style={{ fontSize: 13, color: disabled ? "#bdbdbd" : "#222" }}>1</span>
        <input
          ref={inputRef}
          type="number"
          min={0}
          max={1}
          step={0.1}
          value={Number.isNaN(value) ? "" : String(value).replace(/^0+([1-9])/, '$1')}
          onChange={handleInputChange}
          className={styles.sliderValueInput}
          disabled={disabled}
          aria-label="Temperature value"
          style={{
            width: 48,
            height: 36,
            borderRadius: 8,
            border: "1.5px solid #d1d5db",
            fontSize: 16,
            textAlign: "center",
            outline: "none",
            boxSizing: "border-box",
            transition: "border 0.2s",
          }}
          onFocus={e => e.target.style.border = "2px solid #2563eb"}
          onBlur={e => e.target.style.border = "1.5px solid #d1d5db"}
        />
      </div>
    </div>
  );
  if (hideOverlay) return content;
  return <div className={styles.popupOverlay}>{content}</div>;
};

export default TemperatureSliderPopup;