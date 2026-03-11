import React, { useState } from "react";
import TextField from "./TextField";
import styles from "./TextField.module.css";

// Simple search icon SVG
const SearchIcon = (
  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="11" cy="11" r="8" />
    <path d="m21 21-4.34-4.34" />
  </svg>
);

const TextFieldDemo = () => {
  const [value, setValue] = useState("");
  return (
    <div style={{ maxWidth: 400, margin: "0 auto", background: "#fff", border: "1px solid #eee", borderRadius: 12, padding: 24 }}>
      <h3 style={{ marginBottom: 16, fontSize: 16 }}>Text Field</h3>
      <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
        <div>
          <div className={styles.sectionLabel}>Default</div>
          <TextField placeholder="Enter text..." value={value} onChange={e => setValue(e.target.value)} />
        </div>
        <div>
          <div className={styles.sectionLabel}>Focus (ring-2, ring-blue-300)</div>
          <TextField placeholder="Enter text..." value={value} onChange={e => setValue(e.target.value)} className="ring-2 ring-blue-300" />
        </div>
        <div>
          <div className={styles.sectionLabel}>With Icon</div>
          <TextField placeholder="Search..." icon={SearchIcon} />
        </div>
        <div>
          <div className={styles.sectionLabel}>Disabled</div>
          <TextField placeholder="Enter text..." disabled />
        </div>
      </div>
    </div>
  );
};

export default TextFieldDemo;
