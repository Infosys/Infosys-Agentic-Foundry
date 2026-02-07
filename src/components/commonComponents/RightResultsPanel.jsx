import React from "react";

const RightResultsPanel = ({ styles, results, loading, handleRerun, handleApprove, scrollCardsOnly = false }) => {
  return (
    <div
      className={styles.groundTruthContainer}
      style={{
        flex: 1,
        minWidth: "400px",
        maxWidth: "600px",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        position: "relative",
        minHeight: 0, // Ensure flex children can shrink
      }}>
      <label className={styles.label} style={{ fontWeight: "bold", fontSize: "1.15em", marginBottom: "0.5em" }}>
        Preview Results
      </label>
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          marginBottom: 0,
          paddingBottom: "2em",
        }}>
        {results.queries?.map((q, i) => (
          <div key={i} className={styles.scoreCard}>
            <div className={styles.scoreCardQuery}>
              <span className={`${styles.scoreCardQueryLabel} ${styles.scoreCardQueryLabelConsistency}`}>Query: </span>
              <span className={styles.scoreCardQueryText}>{q}</span>
            </div>
            {results.responses?.[i] && (
              <div className={styles.scoreItemResponse}>
                <span className={styles.scoreItemResponseLabel}>Response:</span>
                <span className={styles.scoreItemResponseText}>{results.responses?.[i]}</span>
              </div>
            )}
          </div>
        ))}
        {/* <div style={{ height: "2em" }}></div> */}
      </div>
      <div
        className={styles.buttonGroup}
        style={{
          justifyContent: "flex-start",
          display: "flex",
          padding: "1.5em 0 1em 0",
        }}>
        <button type="button" onClick={handleApprove} className="iafButton iafButtonPrimary" disabled={loading}>
          Approve
        </button>
        <button type="button" onClick={handleRerun} className="iafButton iafButtonSecondary" disabled={loading}>
          Rerun
        </button>
      </div>
    </div>
  );
};

export default RightResultsPanel;
