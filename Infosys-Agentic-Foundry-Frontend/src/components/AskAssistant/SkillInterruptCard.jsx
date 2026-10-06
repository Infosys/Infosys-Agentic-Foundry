import { useState } from "react";
import styles from "./SkillInterruptCard.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";

/**
 * SkillInterruptCard — Renders when the backend sends interrupt_metadata with
 * interrupt_type === "skill_interrupt".  Shows all matched skills from the
 * routing decision and lets the user approve, modify (pick a different skill
 * via NewCommonDropdown), or reject.
 *
 * Props:
 *  - interruptMetadata  {Object}   Full interrupt_metadata from the response
 *  - messageData        {Object}   Chat message object (passed through for callbacks)
 *  - onSkillFeedback    {Function} Called with (messageData, feedbackValue)
 *                                   feedbackValue: "approve" | "reject" | "<skill_name>"
 *  - fetching           {boolean}  Whether a request is in-flight
 *  - generating         {boolean}  Whether the bot is generating
 */
const SkillInterruptCard = ({
  interruptMetadata,
  messageData,
  onSkillFeedback,
  fetching,
  generating,
}) => {
  const [decided, setDecided] = useState(null); // "approve" | "reject" | "modify" | null
  const [isModifying, setIsModifying] = useState(false);
  const [selectedSkill, setSelectedSkill] = useState("");

  if (!interruptMetadata) return null;

  const {
    available_skills = [],
    matched_skills = [],
    routing_method = "",
    routing_confidence,
    actions = ["approve", "modify", "reject"],
  } = interruptMetadata;

  // All matched skill names
  const matchedNames = matched_skills.map((ms) => ms?.name || ms).filter(Boolean);

  const isLoading = fetching || generating;
  const hasDecided = decided !== null;
  const canApprove = actions.includes("approve");
  const canModify = actions.includes("modify");
  const canReject = actions.includes("reject");

  // Build list of alternative skills (exclude ALL matched skills)
  const otherSkills = available_skills
    .map((s) => (s?.name || s))
    .filter((name) => !matchedNames.includes(name));

  // Format confidence as percentage
  const confidenceDisplay =
    routing_confidence !== undefined && routing_confidence !== null
      ? `${(Number(routing_confidence) * 100).toFixed(0)}%`
      : null;

  // Confidence color class
  const getConfidenceClass = (val) => {
    const num = Number(val);
    if (num >= 0.8) return styles.confidenceHigh;
    if (num >= 0.5) return styles.confidenceMedium;
    return styles.confidenceLow;
  };

  const handleApprove = () => {
    setDecided("approve");
    onSkillFeedback?.(messageData, "approve");
  };

  const handleReject = () => {
    setDecided("reject");
    onSkillFeedback?.(messageData, "reject");
  };

  const handleModifyStart = () => {
    setIsModifying(true);
    setSelectedSkill("");
  };

  const handleModifyConfirm = () => {
    if (!selectedSkill) return;
    setDecided("modify");
    setIsModifying(false);
    onSkillFeedback?.(messageData, selectedSkill);
  };

  const handleModifyCancel = () => {
    setIsModifying(false);
    setSelectedSkill("");
  };

  return (
    <div className={styles.wrapper}>
      <div className={styles.card}>
        {/* ── Header ── */}
        <div className={styles.header}>
          <SVGIcons icon="activity-pulse" width={18} height={18} stroke="#0073CF" />
          <span className={styles.headerTitle}>Skill Routing Verification</span>
          {confidenceDisplay && (
            <span className={`${styles.confidenceBadge} ${getConfidenceClass(routing_confidence)}`}>
              {confidenceDisplay} confidence
            </span>
          )}
        </div>

        {/* ── Skill Routing Info ── */}
        <div className={styles.content}>
          {routing_method && (
            <div className={styles.row}>
              <span className={styles.label}>Routing Method:</span>
              <span className={styles.value}>{routing_method}</span>
            </div>
          )}

          {/* Matched Skills — all skills the router selected */}
          {matched_skills.length > 0 && (
            <div className={styles.matchedSection}>
              <span className={styles.label}>Matched Skills:</span>
              <div className={styles.matchedList}>
                {matched_skills.map((ms, idx) => {
                  const name = ms?.name || ms;
                  const conf = ms?.confidence;
                  const confPct = conf !== undefined && conf !== null ? `${(Number(conf) * 100).toFixed(0)}%` : null;
                  const reasoning = ms?.reasoning || "";
                  return (
                    <div key={`${name}-${idx}`} className={styles.matchedItem}>
                      <div className={styles.matchedItemHeader}>
                        <span className={styles.matchedItemName}>{name}</span>
                        {confPct && (
                          <span className={`${styles.matchedItemConf} ${getConfidenceClass(conf)}`}>
                            {confPct}
                          </span>
                        )}
                      </div>
                      {reasoning && <span className={styles.matchedItemReason}>{reasoning}</span>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* ── Action Buttons / Modify Dropdown ── */}
        <div className={styles.actions}>
          {hasDecided ? (
            <div className={styles.decidedRow}>
              <SVGIcons
                icon={decided === "reject" ? "close" : "circle-check"}
                width={16}
                height={16}
              />
              <span className={styles.decidedText}>
                {decided === "approve"
                  ? `Approved — proceeding with matched skill${matchedNames.length > 1 ? "s" : ""}…`
                  : decided === "reject"
                    ? "Rejected — aborting skill routing"
                    : `Modified — routing to "${selectedSkill}"…`}
              </span>
            </div>
          ) : isModifying ? (
            <div className={styles.modifyRow}>
              {otherSkills.length > 0 ? (
                <div className={styles.dropdownWrap}>
                  <NewCommonDropdown
                    options={otherSkills}
                    selected={selectedSkill}
                    onSelect={(val) => setSelectedSkill(val)}
                    placeholder="Select a skill…"
                    showSearch={otherSkills.length > 5}
                    hideFooter
                  />
                </div>
              ) : (
                <span className={styles.noSkillsText}>No other skills available</span>
              )}
              <button
                className={styles.approveBtn}
                onClick={handleModifyConfirm}
                disabled={isLoading || !selectedSkill || otherSkills.length === 0}
                title="Confirm skill selection"
              >
                <SVGIcons icon="send" width={15} height={15} />
                <span>Confirm</span>
              </button>
              <button
                className={styles.cancelBtn}
                onClick={handleModifyCancel}
                disabled={isLoading}
                title="Cancel"
              >
                <SVGIcons icon="close" width={15} height={15} />
                <span>Cancel</span>
              </button>
            </div>
          ) : (
            <>
              {canApprove && (
                <button
                  className={styles.approveBtn}
                  onClick={handleApprove}
                  disabled={isLoading}
                  title="Approve skill routing"
                >
                  <SVGIcons icon="check" width={15} height={15} stroke="white" />
                  <span>Approve</span>
                </button>
              )}
              {canModify && (
                <button
                  className={styles.modifyBtn}
                  onClick={handleModifyStart}
                  disabled={isLoading}
                  title="Select a different skill"
                >
                  <SVGIcons icon="pen-edit" width={15} height={15} />
                  <span>Change Skill</span>
                </button>
              )}
              {canReject && (
                <button
                  className={styles.rejectBtn}
                  onClick={handleReject}
                  disabled={isLoading}
                  title="Reject skill routing"
                >
                  <SVGIcons icon="close" width={15} height={15} />
                  <span>Reject</span>
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default SkillInterruptCard;
