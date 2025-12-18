import React from "react";
import styles from "../AgentAssignment.module.css";
import SVGIcons from "../../../Icons/SVGIcons";

const ActionButton = ({ 
  icon, 
  onClick, 
  disabled = false, 
  title = "", 
  variant = "primary", // primary, secondary, danger
  className = "",
  width,
  height
}) => {
  const buttonClass = variant === "danger" 
    ? styles.removeButton 
    : styles.updateButton;

  return (
    <button
      onClick={onClick}
      className={`${buttonClass} ${className}`}
      disabled={disabled}
      title={title}
    >
      <SVGIcons 
        icon={icon} 
        width={width || (variant === "secondary" ? "10" : "20")} 
        height={height || (variant === "secondary" ? "10" : "16")} 
      />
    </button>
  );
};

export default ActionButton;