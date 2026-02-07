import React, { useState } from "react";
import styles from "./AgentAssignment.module.css";
import IndividualAgentAssignment from "./IndividualAgentAssignment.jsx";
import GroupAgentAssignment from "./GroupAgentAssignment.jsx";
import RoleAgentAssignment from "./RoleAgentAssignment.jsx";

const AgentAssignment = () => {
  const [activeTab, setActiveTab] = useState("individual"); // State for active sub-tab

  return (
    <div className={styles.containerCss}>
      <div className={styles.agentAssignmentContainer}>
        {/* Sub-tabs Header */}
        <div className={styles.toggleWrapper}>
          <button
            type="button"
            className={`iafTabsBtn ${activeTab === "individual" ? " active" : ""}`}
            onClick={() => setActiveTab("individual")}>
            Individual
          </button>
          <button
            type="button"
            className={`iafTabsBtn ${activeTab === "group" ? " active" : ""}`}
            onClick={() => setActiveTab("group")}>
            Group
          </button>
          <button
            type="button"
            className={`iafTabsBtn ${activeTab === "role" ? " active" : ""}`}
            onClick={() => setActiveTab("role")}>
            Role
          </button>

        </div>

        <div className={styles.listArea}>
          {activeTab === "individual" && <IndividualAgentAssignment />}
          {activeTab === "group" && <GroupAgentAssignment />}
          {activeTab === "role" && <RoleAgentAssignment />}
        </div>
      </div>
    </div>
  );
};

export default AgentAssignment;