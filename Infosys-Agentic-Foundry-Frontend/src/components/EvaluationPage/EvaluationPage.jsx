import React, { useState } from "react";
import Cookies from "js-cookie";
import styles from "./EvaluationPage.module.css";
import EvaluationScore from "../AdminScreen/EvaluationScore";
import AgentsEvaluator from "../AgentsEvaluator";
import UnifiedEvaluationTab from "./UnifiedEvaluationTab";

const EvaluationPage = () => {
  const [activeTab, setActiveTab] = useState("evaluation");
  const [activeSubTab, setActiveSubTab] = useState("groundtruth");
  const [activeMetricsSubTab, setActiveMetricsSubTab] = useState("evaluationRecords");
  const userRole = Cookies.get("role");
  const isAdmin = userRole && userRole.toLowerCase() === "admin";
  const isDeveloper = userRole && userRole.toLowerCase() === "developer";

  return (
    <div style={{ fontFamily: "Arial, sans-serif", marginLeft: 20, marginTop: 20, height: "100vh", overflow: "hidden" }}>
      {/* Header Tabs */}
      <div className={styles.tabHeader}>
        <button className={activeTab === "evaluation" ? "iafTabsBtn active" : "iafTabsBtn"} onClick={() => setActiveTab("evaluation")} style={{ borderRadius: "4px 4px 0 0" }}>
          {isAdmin ? "LLM as Judge" : "LLM as Judge"}
        </button>
        <button className={activeTab === "metrics" ? "iafTabsBtn active" : "iafTabsBtn"} onClick={() => setActiveTab("metrics")} style={{ borderRadius: "4px 4px 0 0" }}>
          Metrics
        </button>
        <button className={activeTab === "unified" ? "iafTabsBtn active" : "iafTabsBtn"} onClick={() => setActiveTab("unified")} style={{ borderRadius: "4px 4px 0 0" }}>
          Evaluation
        </button>
      </div>
      {/* Sub-header Tabs for Evaluation */}
      {activeTab === "unified" && (
        <div className={styles.subHeaderTabs}>
          {/* Ground Truth tab - show for admin OR developer users */}
          {(isAdmin || isDeveloper) && (
            <button
              className={activeSubTab === "groundtruth" ? "iafTabsBtn active" : "iafTabsBtn"}
              style={{ borderRadius: "0 0 0 4px" }}
              onClick={() => setActiveSubTab("groundtruth")}>
              Ground Truth
            </button>
          )}
          <button
            className={activeSubTab === "consistency" ? "iafTabsBtn active" : "iafTabsBtn"}
            style={{ borderRadius: "0 0 4px 0" }}
            onClick={() => setActiveSubTab("consistency")}>
            Consistency
          </button>
        </div>
      )}
      {/* Sub-header Tabs for Metrics */}
      {activeTab === "metrics" && (
        <div className={styles.subHeaderTabs}>
          <button
            className={activeMetricsSubTab === "evaluationRecords" ? "iafTabsBtn active" : "iafTabsBtn"}
            style={{ borderRadius: "0 0 0 4px" }}
            onClick={() => setActiveMetricsSubTab("evaluationRecords")}>
            Evaluation Records
          </button>
          <button className={activeMetricsSubTab === "toolsEfficiency" ? "iafTabsBtn active" : "iafTabsBtn"} onClick={() => setActiveMetricsSubTab("toolsEfficiency")}>
            Tools Efficiency
          </button>
          <button
            className={activeMetricsSubTab === "agentsEfficiency" ? "iafTabsBtn active" : "iafTabsBtn"}
            style={{ borderRadius: "0 0 4px 0" }}
            onClick={() => setActiveMetricsSubTab("agentsEfficiency")}>
            Agents Efficiency
          </button>
        </div>
      )}
      <div className={styles.tabContent}>
        {activeTab === "evaluation" && <AgentsEvaluator />}
        {activeTab === "metrics" && <EvaluationScore activeMetricsSubTab={activeMetricsSubTab} />}
        {activeTab === "unified" && <UnifiedEvaluationTab activeSubTab={activeSubTab} />}
        {/* Ground Truth tab - show for admin OR developer users
        {(isAdmin || isDeveloper) && activeTab === "groundtruth" && <GroundTruth isInAdminScreen={isAdmin} isInDeveloperScreen={isDeveloper} />} */}
      </div>
    </div>
  );
};

export default EvaluationPage;
