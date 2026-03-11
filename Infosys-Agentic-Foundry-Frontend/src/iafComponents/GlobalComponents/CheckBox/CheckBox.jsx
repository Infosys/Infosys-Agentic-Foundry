import React, { useRef } from "react";
import PropTypes from "prop-types";
import styles from "./CheckBox.module.css";

/**
 * CheckBox - A robust, accessible, reusable checkbox for dropdowns and forms.
 * Handles all states: checked, unchecked, disabled, focus, keyboard navigation.
 *
 * Props:
 * - checked: boolean (checked state)
 * - onChange: function (called with new checked state)
 * - disabled: boolean (disable interaction)
 * - label: string (optional, for ARIA and screen readers)
 * - className: string (optional, extra classes)
 * - id: string (optional, for input association)
 * - tabIndex: number (optional, for keyboard nav)
 */
const CheckBox = ({ checked = false, onChange = () => {}, disabled = false, label = "", className = "", id, tabIndex = 0, ...rest }) => {
  const inputRef = useRef(null);

  const handleKeyDown = (e) => {
    if (disabled) return;
    if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      onChange(!checked);
    }
  };

  return (
    <span
      className={styles.checkboxRoot + (checked ? " " + styles.checked : "") + (disabled ? " " + styles.disabled : "") + (className ? " " + className : "")}
      tabIndex={disabled ? -1 : tabIndex}
      role="checkbox"
      aria-checked={checked}
      aria-disabled={disabled}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation();
        if (!disabled) onChange(!checked);
      }}
      onKeyDown={handleKeyDown}
      ref={inputRef}
      {...rest}>
      <input type="checkbox" className={styles.checkboxInput} checked={checked} disabled={disabled} tabIndex={-1} readOnly aria-hidden="true" id={id} />
      <span className={styles.checkboxTick}></span>
    </span>
  );
};

CheckBox.propTypes = {
  checked: PropTypes.bool,
  onChange: PropTypes.func,
  disabled: PropTypes.bool,
  label: PropTypes.string,
  className: PropTypes.string,
  id: PropTypes.string,
  tabIndex: PropTypes.number,
};

export default CheckBox;
