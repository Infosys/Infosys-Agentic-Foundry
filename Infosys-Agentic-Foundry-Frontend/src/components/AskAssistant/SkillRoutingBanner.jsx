import React from "react";
import styles from "./SkillRoutingBanner.module.css";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faBullseye, faRoute, faShieldAlt } from "@fortawesome/free-solid-svg-icons";

/**
 * SkillRoutingBanner - Displays skill routing information for skill_agent responses
 * Shows: skill name, routing method (keyword/llm), confidence level
 *
 * @param {Object} props
 * @param {string} props.skillName - Name of the skill that handled the query
 * @param {string} props.skillDescription - Description of the skill
 * @param {string} props.routingMethod - How the skill was selected ("keyword" | "llm")
 * @param {number} props.routingConfidence - Confidence score 0.0 to 1.0
 */
const SkillRoutingBanner = ({
  skillName,
  skillDescription,
  routingMethod,
  routingConfidence,
}) => {
  // Don't render if no skill info
  if (!skillName) return null;

  // Format confidence as percentage
  const confidencePercent = routingConfidence
    ? Math.round(routingConfidence * 100)
    : null;

  // Determine confidence color based on value
  const getConfidenceClass = () => {
    if (!confidencePercent) return "";
    if (confidencePercent >= 80) return styles.highConfidence;
    if (confidencePercent >= 50) return styles.mediumConfidence;
    return styles.lowConfidence;
  };

  // Format routing method display
  const getRoutingMethodDisplay = () => {
    if (routingMethod === "keyword") return "Keyword Match";
    if (routingMethod === "llm") return "LLM Routing";
    return routingMethod || "Auto";
  };

  return (
    <div className={styles.banner}>
      <div className={styles.bannerContent}>
        <div className={styles.skillInfo}>
          <FontAwesomeIcon icon={faBullseye} className={styles.icon} />
          <span className={styles.label}>Routed to:</span>
          <span className={styles.skillName}>{skillName.replace(/_/g, " ")}</span>
        </div>

        <div className={styles.routingDetails}>
          <div className={styles.routingMethod}>
            <FontAwesomeIcon icon={faRoute} className={styles.smallIcon} />
            <span>{getRoutingMethodDisplay()}</span>
          </div>

          {confidencePercent !== null && (
            <div className={`${styles.confidence} ${getConfidenceClass()}`}>
              <FontAwesomeIcon icon={faShieldAlt} className={styles.smallIcon} />
              <span>{confidencePercent}%</span>
            </div>
          )}
        </div>
      </div>

      {skillDescription && (
        <div className={styles.description}>{skillDescription}</div>
      )}
    </div>
  );
};

export default SkillRoutingBanner;
