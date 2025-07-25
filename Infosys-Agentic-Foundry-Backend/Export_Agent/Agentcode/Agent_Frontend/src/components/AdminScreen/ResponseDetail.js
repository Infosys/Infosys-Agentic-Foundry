import styles from './ResponseDetail.module.css';

// ResponseDetail component
const ResponseDetail = ({ form, onChange, onSubmit, onBack }) => (
  <div className={styles.container}>
    <div className={styles.headerActions}>
      <h2 className={styles.heading}>Edit Response</h2>
      <button
        type="button"
        onClick={onBack}
        className={styles.backButton}
      >Back to Responses</button>
    </div>
    
    <form onSubmit={onSubmit} className={styles.form}>
      <input type="hidden" name="response_id" value={form.response_id} />
      
      <div className={styles.fieldGroup}>
        <div className={styles.fieldGroupTitle}>Original Query</div>
        <label className={styles.label}>Query:</label>
        <textarea name="query" value={form.query} onChange={onChange} className={styles.textarea} />
      </div>
      
      <div className={styles.fieldGroup}>
        <div className={styles.fieldGroupTitle}>Original Response</div>
        <label className={styles.label}>Old Final Response:</label>
        <textarea name="old_final_response" value={form.old_final_response} onChange={onChange} className={styles.textarea} />
        <label className={styles.label}>Old Steps:</label>
        <textarea name="old_steps" value={form.old_steps} onChange={onChange} className={styles.textarea} />
        <label className={styles.label}>Old Response:</label>
        <textarea name="old_response" value={form.old_response} onChange={onChange} className={styles.textarea} />
      </div>
      
      <div className={styles.fieldGroup}>
        <div className={styles.fieldGroupTitle}>Feedback and Updates</div>
        <label className={styles.label}>Feedback:</label>
        <textarea name="feedback" value={form.feedback} onChange={onChange} className={styles.textarea} />
        <label className={styles.label}>New Final Response:</label>
        <textarea name="new_final_response" value={form.new_final_response} onChange={onChange} className={styles.textarea} />
        <label className={styles.label}>New Steps:</label>
        <textarea name="new_steps" value={form.new_steps} onChange={onChange} className={styles.textarea} />
      </div>
      
      <div className={styles.fieldGroup}>
        <label className={styles.checkboxLabel}>
          <input type="checkbox" name="approved" checked={form.approved} onChange={onChange} className={styles.checkbox} />
          Approved
        </label>
      </div>
      
      <div className={styles.buttonRow}>
        <button type="submit" className={styles.submitButton}>Update Response</button>
      </div>
    </form>
  </div>
);
export default ResponseDetail;