import React, { useState } from "react";
import styles from "./EvaluationPage.module.css";
import EvaluationScore from "../AdminScreen/EvaluationScore";
import AgentsEvaluator from "../AgentsEvaluator";
import GroundTruth from "../GroundTruth/GroundTruth";
import ConsistencyTab from "./ConsistencyTab";

const EvaluationPlanScreen = () => {
  const [activeTab, setActiveTab] = useState("evaluation");
  const [activeMetricsSubTab, setActiveMetricsSubTab] = useState("evaluationRecords");
  const [consistencyResponse, setConsistencyResponse] = useState(null);

  // Handler to pass to ConsistencyTab for response
  const handleConsistencyResponse = (response) => {
    setConsistencyResponse(response);
  };

  return (
    <div className={`adminScreen ${styles.sideTabWrapper}`}>
      <nav aria-label="Evaluation Tabs" className={styles.leftNav}>
        <div className={styles.leftNavTabs}>
          {/* LLM as Judge */}
          <button
            className={`${styles.navItem} ${activeTab === "evaluation" ? styles.activeItem : ""}`}
            onClick={() => setActiveTab("evaluation")}
            aria-label="LLM as Judge"
            title="LLM as Judge">
            LLM as Judge
          </button>
          <p className={styles.navSeparator}></p>
          {/* Metrics Label (non-clickable) */}
          <div className={styles.navLabel} title="Metrics">
            Metrics
          </div>

          {/* Evaluation Records - Submenu */}
          <button
            className={`${styles.navSubItem} ${activeTab === "evaluationRecords" ? styles.activeSubItem : ""}`}
            onClick={() => {
              setActiveTab("evaluationRecords");
              setActiveMetricsSubTab("evaluationRecords");
            }}
            aria-label="Evaluation Records"
            title="Evaluation Records">
            <span className={styles.subItemIcon}>›</span>
            <span className={styles.subItemText}>Evaluation Records</span>
          </button>

          {/* Tools Efficiency - Submenu */}
          <button
            className={`${styles.navSubItem} ${activeTab === "toolsEfficiency" ? styles.activeSubItem : ""}`}
            onClick={() => {
              setActiveTab("toolsEfficiency");
              setActiveMetricsSubTab("toolsEfficiency");
            }}
            aria-label="Tools Efficiency"
            title="Tools Efficiency">
            <span className={styles.subItemIcon}>›</span>
            <span className={styles.subItemText}>Tools Efficiency</span>
          </button>

          {/* Agents Efficiency - Submenu */}
          <button
            className={`${styles.navSubItem} ${activeTab === "agentsEfficiency" ? styles.activeSubItem : ""}`}
            onClick={() => {
              setActiveTab("agentsEfficiency");
              setActiveMetricsSubTab("agentsEfficiency");
            }}
            aria-label="Agents Efficiency"
            title="Agents Efficiency">
            <span className={styles.subItemIcon}>›</span>
            <span className={styles.subItemText}>Agents Efficiency</span>
          </button>

          <p className={styles.navSeparator}></p>

          {/* Evaluation Label (non-clickable) */}
          <div className={styles.navLabel} title="Evaluation">
            Evaluation
          </div>

          {/* Ground Truth - Submenu */}
          <button
            className={`${styles.navSubItem} ${activeTab === "groundtruth" ? styles.activeSubItem : ""}`}
            onClick={() => setActiveTab("groundtruth")}
            aria-label="Ground Truth"
            title="Ground Truth">
            <span className={styles.subItemIcon}>›</span>
            <span className={styles.subItemText}>Ground Truth</span>
          </button>

          {/* Consistency - Submenu */}
          <button
            className={`${styles.navSubItem} ${activeTab === "consistency" ? styles.activeSubItem : ""}`}
            onClick={() => setActiveTab("consistency")}
            aria-label="Consistency"
            title="Consistency">
            <span className={styles.subItemIcon}>›</span>
            <span className={styles.subItemText}>Consistency</span>
          </button>

          <p className={styles.navSeparator}></p>
        </div>
      </nav>
      {/* Right: Tab Content - fills all available space */}
      {activeTab === "evaluation" && (
        <div className={styles.rightTabContent}>
          <div className={styles.rightTabContent}>
            <AgentsEvaluator />
          </div>
        </div>
      )}
      {(activeTab === "evaluationRecords" || activeTab === "toolsEfficiency" || activeTab === "agentsEfficiency") && (
        <div className={styles.rightTabContent}>
          <EvaluationScore activeMetricsSubTab={activeMetricsSubTab} />
        </div>
      )}
      {activeTab === "groundtruth" && (
        <div className={styles.rightTabContent}>
          <GroundTruth />
        </div>
      )}
      {activeTab === "consistency" && (
        <div className={styles.rightTabContent}>
          <div className={styles.consistencySplitContainer}>
            <div className={styles.consistencyFormPanel}>
              <ConsistencyTab onResponse={handleConsistencyResponse} />
            </div>
            {consistencyResponse && (
              <div className={styles.consistencyResponsePanel}>
                <h3>Response</h3>
                <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{consistencyResponse}</pre>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default EvaluationPlanScreen;
