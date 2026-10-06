import React from "react";
import SVGIcons from "../../Icons/SVGIcons";
import { isUnconfiguredCostModel } from "../../utils/modelUtils";
import styles from "./UnconfiguredModelCostWarning.module.css";

const UnconfiguredModelCostWarning = ({ selectedModel, unconfiguredCostModels, className = "" }) => {
  if (!isUnconfiguredCostModel(selectedModel, unconfiguredCostModels)) {
    return null;
  }

  return (
    <div className={`${styles.warning} ${className}`.trim()} role="status">
      <span className={styles.icon} aria-hidden="true">
        <SVGIcons icon="warnings" width={14} height={14} color="#d97706" />
      </span>
      <span>
        Admin has not configured the model cost for <strong>{selectedModel}</strong>.
      </span>
    </div>
  );
};

export default UnconfiguredModelCostWarning;
