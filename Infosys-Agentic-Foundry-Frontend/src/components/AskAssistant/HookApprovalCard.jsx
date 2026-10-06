import { useEffect, useMemo, useState } from "react";
import styles from "./HookApprovalCard.module.css";
import SVGIcons from "../../Icons/SVGIcons";

/**
 * HookApprovalCard — Renders when the backend sends interrupt_metadata with
 * interrupt_type === "hook_approval".  Shows the reason a lifecycle hook or
 * approval rule triggered, the tool + args that need approval, and
 * action buttons driven by the backend `actions` array.
 *
 * Props:
 *  - interruptMetadata  {Object}   The full interrupt_metadata from the response
 *  - messageData        {Object}   The chat message object (passed through for callbacks)
 *  - onApprove          {Function} Called when user clicks Approve
 *  - onReject           {Function} Called when user clicks Reject
 *  - fetching           {boolean}  Whether a request is in-flight
 *  - generating         {boolean}  Whether the bot is generating
 */
const HookApprovalCard = ({
  interruptMetadata,
  messageData,
  onApprove,
  onReject,
  fetching,
  generating,
}) => {
  const [decided, setDecided] = useState(null); // "approve" | "reject" | null

  const {
    tool_name = "",
    tool_args = {},
    reason = "",
    actions = ["approve", "reject"],
    urgency,
    hook_event,
    rule_type,
  } = interruptMetadata || {};

  const interruptSignature = useMemo(
    () => JSON.stringify({ tool_name, tool_args, reason, actions, urgency, hook_event, rule_type }),
    [tool_name, tool_args, reason, actions, urgency, hook_event, rule_type]
  );

  useEffect(() => {
    setDecided(null);
  }, [interruptSignature]);

  if (!interruptMetadata) return null;

  const isLoading = fetching || generating;
  const hasDecided = decided !== null;

  const handleApprove = () => {
    setDecided("approve");
    onApprove?.(messageData);
  };

  const handleReject = () => {
    setDecided("reject");
    onReject?.(messageData);
  };

  // Urgency badge color mapping
  const urgencyColor = {
    low: styles.urgencyLow,
    medium: styles.urgencyMedium,
    high: styles.urgencyHigh,
    critical: styles.urgencyCritical,
  };

  return (
    <div className={styles.wrapper}>
      <div className={styles.card}>
        {/* ── Header ── */}
        <div className={styles.header}>
          <SVGIcons icon="clipboard-check" width={18} height={18} stroke="#0073CF" />
          <span className={styles.headerTitle}>Approval Required</span>
          {urgency && (
            <span className={`${styles.urgencyBadge} ${urgencyColor[urgency] || styles.urgencyMedium}`}>
              {urgency}
            </span>
          )}
        </div>

        {/* ── Reason ── */}
        {reason && (
          <div className={styles.reasonRow}>
            <SVGIcons icon="info-modern" width={15} height={15} />
            <span className={styles.reasonText}>{reason}</span>
          </div>
        )}

        {/* ── Tool Info ── */}
        <div className={styles.content}>
          <div className={styles.row}>
            <span className={styles.label}>Tool:</span>
            <span className={styles.value}>{tool_name}</span>
          </div>

          {/* Hook event / rule type context (optional) */}
          {(hook_event || rule_type) && (
            <div className={styles.row}>
              <span className={styles.label}>Triggered by:</span>
              <span className={styles.value}>
                {rule_type ? `${rule_type}` : ""}
                {rule_type && hook_event ? " · " : ""}
                {hook_event ? `${hook_event}` : ""}
              </span>
            </div>
          )}

          {/* Arguments (read-only display) */}
          {Object.keys(tool_args).length > 0 && (
            <>
              <div className={styles.row}>
                <span className={styles.label}>Arguments:</span>
              </div>
              <div className={styles.argsList}>
                {Object.entries(tool_args).map(([key, val]) => (
                  <div className={styles.argItem} key={key}>
                    <span className={styles.argKey}>{key}:</span>
                    <span className={styles.argValue}>
                      {typeof val === "object" ? JSON.stringify(val, null, 2) : String(val ?? "")}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* ── Action Buttons ── */}
        <div className={styles.actions}>
          {hasDecided ? (
            <div className={styles.decidedRow}>
              <SVGIcons
                icon={decided === "approve" ? "circle-check" : "close"}
                width={16}
                height={16}
              />
              <span className={styles.decidedText}>
                {decided === "approve" ? "Approved — executing…" : "Rejected — aborting tool call"}
              </span>
            </div>
          ) : (
            <>
              {actions.includes("approve") && (
                <button
                  className={styles.approveBtn}
                  onClick={handleApprove}
                  disabled={isLoading}
                  title="Approve tool execution"
                >
                  <SVGIcons icon="check" width={15} height={15} stroke="white" />
                  <span>Approve</span>
                </button>
              )}
              {actions.includes("reject") && (
                <button
                  className={styles.rejectBtn}
                  onClick={handleReject}
                  disabled={isLoading}
                  title="Reject tool execution"
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

export default HookApprovalCard;
