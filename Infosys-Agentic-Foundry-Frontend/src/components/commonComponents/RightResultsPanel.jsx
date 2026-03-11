import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";

const RightResultsPanel = ({ styles, sliderStyles, results, loading, actionLoading = null, handleRerun, handleApprove, scrollCardsOnly = false }) => {
  return (
    <>
      {/* Results Content - Scrollable area */}
      <div className={styles.sliderContent}>
        <div className={styles.scrollableResults}>
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
        </div>
      </div>

      {/* Slider Footer - Matches ResourceSlider exactly */}
      <div className={sliderStyles.sliderFooter}>
        <div className={sliderStyles.sliderFooterButtons}>
          <IAFButton type="primary" onClick={handleApprove} disabled={loading} loading={actionLoading === "approve"}>
            Approve
          </IAFButton>
          <IAFButton type="secondary" onClick={handleRerun} disabled={loading} loading={actionLoading === "rerun"}>
            Rerun
          </IAFButton>
        </div>
      </div>
    </>
  );
};

export default RightResultsPanel;
