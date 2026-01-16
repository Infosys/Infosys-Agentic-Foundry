import React from "react";
import styles from "../AgentAssignment.module.css";

const FormInput = ({
  label,
  type = "text",
  value,
  onChange,
  placeholder = "",
  required = false,
  error = "",
  disabled = false,
  className = "",
  ...props
}) => {
  return (
    <div className={styles.controlGroup}>
      {label && (
        <label className={styles.controlLabel}>
          {label} {required && "*"}
        </label>
      )}
      <input
        type={type}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        className={`${styles.textInput} ${className}`}
        required={required}
        disabled={disabled}
        {...props}
      />
      {error && <div className={styles.errorMessage}>{error}</div>}
    </div>
  );
};

export default FormInput;