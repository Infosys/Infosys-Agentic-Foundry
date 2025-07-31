import React, { useState } from "react";
import Cookies from "js-cookie";
import styles from "./EvaluationPage.module.css";
import EvaluationScore from "../AdminScreen/EvaluationScore";
import AgentsEvaluator from "../AgentsEvaluator";
import GroundTruth from "../GroundTruth/GroundTruth";

const EvaluationPage = () => {
  const [activeTab, setActiveTab] = useState("evaluation");
  const userRole = Cookies.get("role");
  const isAdmin = userRole && userRole.toLowerCase() === "admin";

  return (
    <div style={{ fontFamily: "Arial, sans-serif", marginLeft: 20, marginTop: 20, height: '100vh', overflow: 'hidden' }}>
      <div className={styles.tabHeader}>
        <button 
          className={activeTab === "evaluation" ? styles.activeTab : styles.tab} 
          onClick={() => setActiveTab("evaluation")}
        >
          {isAdmin ? "LLM as Judge" : "LLM as Judge"}
        </button>
        <button 
          className={activeTab === "metrics" ? styles.activeTab : styles.tab} 
          onClick={() => setActiveTab("metrics")}
        >
          Metrics
        </button>
        
        {/* Ground Truth tab - Only show for admin users */}
        {isAdmin && (
          <button 
            className={activeTab === "groundtruth" ? styles.activeTab : styles.tab} 
            onClick={() => setActiveTab("groundtruth")}
          >
            Ground Truth
          </button>
        )}
      </div>

      <div className={styles.tabContent}>
        {activeTab === "evaluation" && <AgentsEvaluator />}
        
        {activeTab === "metrics" && <EvaluationScore />}
        
        {/* Ground Truth content - Only show for admin users */}
        {isAdmin && activeTab === "groundtruth" && <GroundTruth isInAdminScreen={true} />}
      </div>
    </div>
  );
};

export default EvaluationPage;
