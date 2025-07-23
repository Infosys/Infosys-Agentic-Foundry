import React from "react";
import styles from "./Toggle.module.css";

const Toggle = (props) => {
  const { onChange, value } = props;
  return (
    <label className={styles.toggleSwitch}>
      <input type="checkbox" onChange={onChange} checked={value} value={value} />
      <span className={styles.slider}></span>
    </label>
  );
};

export default Toggle;
