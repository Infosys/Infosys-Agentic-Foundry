// ResponsesList component
import React from "react";
import styles from './ResponseList.module.css';

const ResponsesList = ({ responses, onSelect, onBack, agentName }) => {
  // Ensure responses is always an array
  const safeResponses = Array.isArray(responses) ? responses : [];
  return (
    <div className={styles.container}>
      <div className={styles.headerActions}>
        <h2 className={styles.heading}>Agent Responses</h2>
        <button
          onClick={onBack}
          className={styles.backButton}
        >
          Back to Agents
        </button>
      </div>
      <div><strong> Agent:</strong> <span style={{ fontWeight: "normal" }}>{agentName || "--"}</span></div>
      {safeResponses.length > 0 ? (
        <div className={styles.list}>
          {safeResponses.map((r) => (
            <button
              key={r.response_id}
              onClick={() => onSelect(r.response_id)}
              className={styles.responseButton}
            >
              {r.feedback || "Response " + r.response_id}
            </button>
          ))}
        </div>
      ) : (
        <div className={styles.emptyState}>
          <p className={styles.emptyMessage}>No responses available for this agent.</p>
        </div>
      )}
    </div>
  );
};

export default ResponsesList;