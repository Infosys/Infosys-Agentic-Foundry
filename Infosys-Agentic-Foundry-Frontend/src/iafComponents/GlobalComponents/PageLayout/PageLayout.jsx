import React from "react";
import styles from "./PageLayout.module.css";

/**
 * PageLayout - Standard page layout wrapper for consistent scrolling behavior.
 *
 * This component ensures that any page content wrapped inside it will:
 * - Fill available space from parent (pageContainer)
 * - Pass flex behavior down to children (listWrapper)
 * - Enable proper scroll behavior automatically
 *
 * WHY THIS EXISTS:
 * - pageContainer uses flex layout
 * - listWrapper needs to be a flex child to calculate scroll height
 * - Any wrapper div between them breaks the flex chain
 * - This component bridges that gap by passing flex properties down
 *
 * USAGE:
 * ```jsx
 * import PageLayout from "../../iafComponents/GlobalComponents/PageLayout";
 *
 * <PageLayout>
 *   <SummaryLine />
 *   <div className="listWrapper">
 *     {/* Your scrollable content *\/}
 *   </div>
 * </PageLayout>
 * ```
 *
 * RULES:
 * 1. Always wrap page content in <PageLayout> when inside pageContainer
 * 2. Put your scrollable content inside a div with className="listWrapper"
 * 3. Never add height/overflow styles to intermediate wrappers
 *
 * @param {React.ReactNode} children - Page content
 * @param {string} className - Optional additional class for custom styling
 */
const PageLayout = ({ children, className = "" }) => {
  return <div className={`${styles.pageLayout} ${className}`.trim()}>{children}</div>;
};

export default PageLayout;
