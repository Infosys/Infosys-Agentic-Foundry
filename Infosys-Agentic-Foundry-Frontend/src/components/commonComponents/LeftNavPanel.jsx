import React from "react";

/**
 * Generic left-side navigation/form panel for any page.
 * Props:
 * - styles: CSS module object
 * - title: string (panel title)
 * - children: form/content JSX
 * - buttonGroup: JSX for action buttons (optional)
 * - containerStyle: style object for outer div (optional)
 */
const LeftNavPanel = ({ styles, title = "Panel", children, buttonGroup, containerStyle = {} }) => (
  <div className={styles.groundTruthContainer}>
    <div className="iafPageSubHeader">
      <h6>{title}</h6>
    </div>
    <form onSubmit={(e) => e.preventDefault()} className={styles.form}>
      {children}
      {/* <div style={{ display: "flex", gap: "16px", marginTop: "24px" }}>{buttonGroup && buttonGroup}</div> */}
    </form>
  </div>
);

export default LeftNavPanel;
