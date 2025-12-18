import React from "react";
import GroundTruth from "../GroundTruth/GroundTruth";
import ConsistencyTab from "./ConsistencyTab";
import styles from "../GroundTruth/GroundTruth.module.css";

const UnifiedEvaluationTab = ({ activeSubTab }) => {
  return (
    <div className={styles.groundTruthWrapper}>
      <div className={styles.groundTruthContainer}>
        <div
          style={{
            background: "#fff",
            borderRadius: "4px",
            border: "1px solid #e0e0e0",
            boxShadow: "0 2px 8px rgba(0,124,195,0.08)",
            padding: "24px",
            margin: "0 auto",
            maxWidth: "1100px"
          }}
        >
          {/* Render content based on sub-tab */}
          {activeSubTab === "groundtruth" && <GroundTruth/>}
          {activeSubTab === "consistency" && <ConsistencyTab />}
        </div>
      </div>
    </div>
  );
};

export default UnifiedEvaluationTab;
