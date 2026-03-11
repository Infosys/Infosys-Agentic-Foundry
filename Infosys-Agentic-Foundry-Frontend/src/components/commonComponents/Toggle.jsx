import React from "react";
import styles from "./Toggle.module.css";

const Toggle = (props) => {
  const { onChange, value, disabled = false } = props;
  return (
    <label className={`${styles.toggleSwitch} ${disabled ? styles.disabled : ""}`}>
      <input type="checkbox" onChange={onChange} checked={value} value={value} disabled={disabled} />
      <span className={styles.slider}></span>
    </label>
  );
};

export default Toggle;
