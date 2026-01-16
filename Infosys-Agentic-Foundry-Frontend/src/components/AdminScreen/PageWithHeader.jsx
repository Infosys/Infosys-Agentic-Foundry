import React from "react";
import styles from "./PageWithHeader.module.css";

const PageWithHeader = ({ heading, children }) => (
  <div style={{ padding: "24px", background: "#fff", minHeight: "calc(100vh - 45px)" }}>
    <div style={{ marginBottom: 20 }}>
      <h6 className={styles.h6Heading}>{heading}</h6>
    </div>
    {children}
  </div>
);

export default PageWithHeader;
