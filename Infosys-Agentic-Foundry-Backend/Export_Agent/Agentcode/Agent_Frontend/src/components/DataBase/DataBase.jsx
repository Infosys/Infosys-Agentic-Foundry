import React from "react";
import styles from './DataBase.module.css';

const DataBase=()=>{
return(
    <>
    <div className={styles.container}>
 <div className={styles.headerActions}>
      <h2 className={styles.heading}>Data Connector</h2>
    </div>
    <form onSubmit={""} className={styles.form}>
      <input type="hidden" name="response_id" value={""} />
      
      <div className={styles.fieldGroup}>
        <div className={styles.fieldGroupTitle}>Original Query</div>
        <label className={styles.label}>Query:</label>
        <textarea name="query" value={""} onChange={""} className={styles.textarea} />
      </div>
      
      <div className={styles.fieldGroup}>
        <div className={styles.fieldGroupTitle}>Original Response</div>
        <label className={styles.label}>Old Final Response:</label>
        <textarea name="old_final_response" value={""} onChange={""} className={styles.textarea} />
        <label className={styles.label}>Old Steps:</label>
        <textarea name="old_steps" value={""} onChange={""} className={styles.textarea} />
        <label className={styles.label}>Old Response:</label>
        <textarea name="old_response" value={""} onChange={""} className={styles.textarea} />
      </div>
      
      <div className={styles.fieldGroup}>
        <div className={styles.fieldGroupTitle}>Feedback and Updates</div>
        <label className={styles.label}>Feedback:</label>
        <textarea name="feedback" value={""} onChange={""} className={styles.textarea} />
        <label className={styles.label}>New Final Response:</label>
        <textarea name="new_final_response" value={""} onChange={""} className={styles.textarea} />
        <label className={styles.label}>New Steps:</label>
        <textarea name="new_steps" value={""} onChange={""} className={styles.textarea} />
      </div>
      
      <div className={styles.fieldGroup}>
        <label className={styles.checkboxLabel}>
          <input type="checkbox" name="approved" checked={""} onChange={""} className={styles.checkbox} />
          Approved
        </label>
      </div>
      
      <div className={styles.buttonRow}>
        <button type="submit" className={styles.submitButton}>Update Response</button>
      </div>
    </form>
  </div>
    </>
)
}
export default DataBase