import React from "react";
import styles from "./Skeleton.module.css";

/**
 * Skeleton Component - Modern loading placeholder
 * 
 * Displays animated skeleton placeholders while content is loading.
 * Supports multiple variants for different UI elements.
 * 
 * @param {string} variant - "text" | "circular" | "rectangular" | "card" | "avatar"
 * @param {number|string} width - Width of the skeleton (default: 100%)
 * @param {number|string} height - Height of the skeleton (default: auto based on variant)
 * @param {number} count - Number of skeleton elements to render (for lists)
 * @param {string} className - Additional CSS classes
 * @param {boolean} animation - Enable/disable shimmer animation (default: true)
 */
const Skeleton = ({
  variant = "text",
  width,
  height,
  count = 1,
  className = "",
  animation = true,
}) => {
  // Default sizes based on variant
  const getDefaultStyles = () => {
    const baseStyles = {
      width: width || "100%",
    };

    switch (variant) {
      case "circular":
      case "avatar":
        return {
          ...baseStyles,
          width: width || 40,
          height: height || width || 40,
        };
      case "rectangular":
        return {
          ...baseStyles,
          height: height || 120,
        };
      case "card":
        return {
          ...baseStyles,
          height: height || 140,
        };
      case "text":
      default:
        return {
          ...baseStyles,
          height: height || 16,
        };
    }
  };

  const style = getDefaultStyles();

  const getVariantClass = () => {
    switch (variant) {
      case "circular":
      case "avatar":
        return styles.circular;
      case "rectangular":
        return styles.rectangular;
      case "card":
        return styles.card;
      case "text":
      default:
        return styles.text;
    }
  };

  const skeletons = Array.from({ length: count }, (_, index) => (
    <div
      key={index}
      className={`${styles.skeleton} ${getVariantClass()} ${animation ? styles.animated : ""} ${className}`}
      style={{
        width: typeof style.width === "number" ? `${style.width}px` : style.width,
        height: typeof style.height === "number" ? `${style.height}px` : style.height,
      }}
      aria-busy="true"
      aria-live="polite"
    />
  ));

  return count > 1 ? <div className={styles.skeletonGroup}>{skeletons}</div> : skeletons[0];
};

/**
 * SkeletonCard - Pre-built skeleton for card layouts
 */
export const SkeletonCard = ({ className = "" }) => (
  <div className={`${styles.skeletonCard} ${className}`}>
    <div className={styles.skeletonCardHeader}>
      <Skeleton variant="circular" width={40} height={40} />
      <div className={styles.skeletonCardHeaderText}>
        <Skeleton variant="text" width="60%" height={14} />
        <Skeleton variant="text" width="40%" height={12} />
      </div>
    </div>
    <Skeleton variant="text" width="100%" height={12} />
    <Skeleton variant="text" width="80%" height={12} />
    <div className={styles.skeletonCardFooter}>
      <Skeleton variant="text" width={60} height={24} />
      <div className={styles.skeletonCardActions}>
        <Skeleton variant="circular" width={28} height={28} />
        <Skeleton variant="circular" width={28} height={28} />
      </div>
    </div>
  </div>
);

/**
 * SkeletonList - Pre-built skeleton for list items
 */
export const SkeletonList = ({ count = 5, className = "" }) => (
  <div className={`${styles.skeletonList} ${className}`}>
    {Array.from({ length: count }, (_, index) => (
      <div key={index} className={styles.skeletonListItem}>
        <Skeleton variant="circular" width={32} height={32} />
        <div className={styles.skeletonListContent}>
          <Skeleton variant="text" width="70%" height={14} />
          <Skeleton variant="text" width="50%" height={12} />
        </div>
      </div>
    ))}
  </div>
);

/**
 * SkeletonGrid - Pre-built skeleton for card grids
 */
export const SkeletonGrid = ({ count = 6, className = "" }) => (
  <div className={`${styles.skeletonGrid} ${className}`}>
    {Array.from({ length: count }, (_, index) => (
      <SkeletonCard key={index} />
    ))}
  </div>
);

export default Skeleton;
