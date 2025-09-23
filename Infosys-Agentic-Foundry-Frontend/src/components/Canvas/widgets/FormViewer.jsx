import React from 'react';
import styles from './FormViewer.module.css';
import SVGIcons from '../../../Icons/SVGIcons';

const FormViewer = ({ content, messageId }) => {
  // Simple form renderer for demo purposes
  const renderForm = () => {
    if (typeof content === 'object' && content.fields) {
      return (
        <form className={styles.form}>
          {content.fields.map((field, index) => (
            <div key={index} className={styles.fieldGroup}>
              <label className={styles.label}>{field.label}</label>
              {field.type === 'textarea' ? (
                <textarea 
                  className={styles.textarea}
                  placeholder={field.placeholder}
                  defaultValue={field.value}
                />
              ) : (
                <input 
                  type={field.type || 'text'}
                  className={styles.input}
                  placeholder={field.placeholder}
                  defaultValue={field.value}
                />
              )}
            </div>
          ))}
          <button type="submit" className={styles.submitButton}>
            Submit
          </button>
        </form>
      );
    }
    
    return (
      <div className={styles.fallback}>
        <pre className={styles.fallbackContent}>
          {typeof content === 'string' ? content : JSON.stringify(content, null, 2)}
        </pre>
      </div>
    );
  };

  return (
    <div className={styles.formViewer}>
      {/* Toolbar */}
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <div className={styles.contentTag}>
            <svg width="14" height="14" viewBox="0 0 20 20" fill="none">
              <rect x="3" y="4" width="14" height="12" rx="2" stroke="#007acc" strokeWidth="1.5" fill="none"/>
              <line x1="6" y1="8" x2="14" y2="8" stroke="#007acc" strokeWidth="1.5"/>
              <line x1="6" y1="10" x2="11" y2="10" stroke="#007acc" strokeWidth="1.5"/>
              <line x1="6" y1="12" x2="14" y2="12" stroke="#007acc" strokeWidth="1.5"/>
            </svg>
            <span>Form</span>
          </div>
        </div>
      </div>

      {/* Form Content */}
      <div className={styles.formContent}>
        {renderForm()}
      </div>
    </div>
  );
};

export default FormViewer;
