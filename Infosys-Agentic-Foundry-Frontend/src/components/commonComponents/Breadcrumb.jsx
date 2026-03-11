import React from "react";
import styles from "./Breadcrumb.module.css";
import SVGIcons from "../../Icons/SVGIcons";

/**
 * Breadcrumb component for hierarchical navigation display
 *
 * @param {Object} props
 * @param {Array} props.items - Array of breadcrumb items [{label: string, onClick?: function}]
 * @param {string} props.separator - Separator character/icon (default: "/")
 *
 * Example usage:
 *   <Breadcrumb items={[
 *     { label: "Admin", onClick: () => navigate("/admin") },
 *     { label: "Learning" },
 *     { label: "Response" }
 *   ]} />
 *
 * Displays: Admin / Learning / Response
 */
const Breadcrumb = ({ items = [], separator = "/" }) => {
  if (!items || items.length === 0) return null;

  return (
    <nav className={styles.breadcrumb} aria-label="Breadcrumb navigation">
      <ol className={styles.breadcrumbList}>
        {items.map((item, index) => {
          const isLast = index === items.length - 1;
          const isClickable = !isLast && typeof item.onClick === "function";

          return (
            <li key={index} className={styles.breadcrumbItem}>
              {isClickable ? (
                <button type="button" onClick={item.onClick} className={styles.breadcrumbLink} aria-current={isLast ? "page" : undefined}>
                  {item.label}
                </button>
              ) : (
                <span className={`${styles.breadcrumbText} ${isLast ? styles.breadcrumbCurrent : ""}`} aria-current={isLast ? "page" : undefined}>
                  {item.label}
                </span>
              )}

              {!isLast && (
                <span className={styles.breadcrumbSeparator} aria-hidden="true">
                  {separator === "chevron" ? <SVGIcons icon="chevron-right" width={14} height={14} stroke="var(--text-muted)" /> : separator}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
};

export default Breadcrumb;
